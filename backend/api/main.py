# Copyright (c) 2025 Meldra AI Ltd. All rights reserved.
# This software is proprietary and confidential. Unauthorised use is prohibited.
"""FastAPI backend for LakeMind / Meldra AI
All endpoints secured with custom JWT MFA authentication.

Environment variables:
- RESEND_API_KEY         : Resend.com API key for email OTP delivery
- JWT_SECRET_KEY         : Long random string for signing JWT tokens
- JWT_ALGORITHM          : HS256 (default)
- GRAPH_DB_HOST/PORT/USER/PASSWORD/NAME : PostgreSQL connection for auth schema
- CORS_ALLOW_ORIGINS     : Comma-separated allowed origins

Run with:
    uvicorn api.main:app --port 8000 --host 0.0.0.0
"""
from __future__ import annotations

import os
import json
import shutil
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
import pandas as pd

from fastapi import FastAPI, Depends, HTTPException, status, Request, UploadFile, File, Cookie
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from jose import jwt as jose_jwt, JWTError
from pydantic import BaseModel, EmailStr, field_validator
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# ── Auth DB & MFA service ────────────────────────────────────────────────────
import sys, os as _os
_sys_path_root = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
if _sys_path_root not in sys.path:
    sys.path.insert(0, _sys_path_root)

from auth_db import (
    init_auth_schema,
    create_user,
    get_user_by_email,
    get_user_by_id,
    mark_user_verified,
    update_last_login,
    generate_otp,
    store_mfa_token,
    verify_mfa_token,
    can_resend_otp,
    create_session,
    validate_refresh_token,
    revoke_session,
    log_audit_pg,
    get_audit_logs_pg,
    verify_password,
)
from mfa_service import send_email_otp

# Import existing agent creator
try:
    from agent import create_iceberg_agent  # type: ignore
except Exception as e:
    create_iceberg_agent = None  # type: ignore

# ── JWT Configuration ────────────────────────────────────────────────────────
JWT_SECRET = os.environ.get("JWT_SECRET_KEY", "CHANGE_ME_USE_A_LONG_RANDOM_STRING_IN_PROD")
JWT_ALGORITHM = os.environ.get("JWT_ALGORITHM", "HS256")
JWT_ACCESS_EXPIRE_MINUTES = int(os.environ.get("JWT_ACCESS_TOKEN_EXPIRE_MINUTES", 15))

app = FastAPI(
    title="Meldra AI — LakeMind Iceberg API",
    version="1.0.0",
    docs_url="/docs",
    description="Proprietary API. Copyright 2025 Meldra AI Ltd. All rights reserved.",
)

# Allow calling from frontend origin
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.environ.get("CORS_ALLOW_ORIGINS", "*").split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["Authorization", "Content-Type", "X-Tenant-Tier", "X-Tenant-ID"],
)

# ─────────────────────────────────────────
# AUDIT LOG (delegates to PostgreSQL via auth_db)
# ─────────────────────────────────────────
def log_audit(user_id: str, tier: str, action: str, details: str, status: str):
    log_audit_pg(user_id=user_id, tier=tier, action=action, details=details, status=status)

@app.on_event("startup")
def startup_event():
    init_auth_schema()
    try:
        from graph_db import init_graph_tables
        init_graph_tables()
    except Exception as e:
        print(f"[api/main] Failed to initialize graph tables on startup: {e}")

# ─────────────────────────────────────────
# PYDANTIC SCHEMAS
# ─────────────────────────────────────────
class ChatRequest(BaseModel):
    messages: List[Dict[str, str]]
    prompt: str

class ChatResponse(BaseModel):
    output: str

class AWSConfigRequest(BaseModel):
    region: str
    s3_warehouse_uri: str
    access_key_id: Optional[str] = None
    secret_access_key: Optional[str] = None

class IngestRequest(BaseModel):
    namespace: str
    table_name: str
    file_path: str
    schema_json: List[Dict[str, str]]

class CypherRequest(BaseModel):
    graph_name: str
    query: str

# ── Auth Schemas ─────────────────────────
class RegisterRequest(BaseModel):
    email: str
    password: str
    mfa_method: str = "email"   # only 'email' for now

    @field_validator("password")
    @classmethod
    def _strong_password(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters.")
        if not any(c.isupper() for c in v):
            raise ValueError("Password must contain at least one uppercase letter.")
        if not any(c.isdigit() for c in v):
            raise ValueError("Password must contain at least one number.")
        return v

class LoginRequest(BaseModel):
    email: str
    password: str

class VerifyMFARequest(BaseModel):
    temp_token: str   # opaque token identifying the pending login session
    code: str         # 6-digit OTP

class ResendOTPRequest(BaseModel):
    temp_token: str

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    refresh_token: str
    user: Dict[str, Any]

# ─────────────────────────────────────────
# JWT HELPERS
# ─────────────────────────────────────────
def _create_access_token(data: Dict[str, Any]) -> str:
    payload = data.copy()
    payload["exp"] = datetime.utcnow() + timedelta(minutes=JWT_ACCESS_EXPIRE_MINUTES)
    payload["iat"] = datetime.utcnow()
    payload["type"] = "access"
    return jose_jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def _create_temp_token(user_id: str, purpose: str = "mfa") -> str:
    """Short-lived token used to identify a pending MFA session (5 min)."""
    payload = {
        "sub": user_id,
        "purpose": purpose,
        "exp": datetime.utcnow() + timedelta(minutes=5),
        "type": "temp",
    }
    return jose_jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def _decode_temp_token(token: str) -> str:
    """Decode temp token, return user_id or raise 401."""
    try:
        payload = jose_jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        if payload.get("type") != "temp":
            raise HTTPException(status_code=401, detail="Invalid token type")
        return payload["sub"]
    except JWTError:
        raise HTTPException(status_code=401, detail="Token expired or invalid. Please log in again.")


# ─────────────────────────────────────────
# AUTH MIDDLEWARE (protects API endpoints)
# ─────────────────────────────────────────
def get_current_user(request: Request) -> Dict[str, Any]:
    """Validates the Bearer JWT and returns the user payload."""
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated. Please log in.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token = auth_header.split(" ", 1)[1]
    try:
        payload = jose_jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        if payload.get("type") != "access":
            raise HTTPException(status_code=401, detail="Invalid token type")
        return payload
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token expired or invalid. Please log in again.",
            headers={"WWW-Authenticate": "Bearer"},
        )

# ─────────────────────────────────────────
# AUTH ENDPOINTS
# ─────────────────────────────────────────

@app.post("/auth/register", tags=["Auth"])
async def register(payload: RegisterRequest, request: Request):
    """Step 1 of registration: create account + send email OTP."""
    # Extract client IP address
    reg_ip = request.headers.get("x-forwarded-for") or request.headers.get("x-real-ip")
    if reg_ip:
        reg_ip = reg_ip.split(",")[0].strip()
    else:
        reg_ip = request.client.host if request.client else "127.0.0.1"
        
    # Extract country geography
    reg_country = (
        request.headers.get("cf-ipcountry") or 
        request.headers.get("x-vercel-ip-country") or 
        request.headers.get("x-country-code") or 
        "Unknown"
    )

    try:
        user = create_user(
            email=payload.email,
            password=payload.password,
            mfa_method=payload.mfa_method,
            tier="trial",
            reg_ip=reg_ip,
            reg_country=reg_country,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Generate and send OTP
    code = generate_otp()
    store_mfa_token(str(user["id"]), code, purpose="register")

    try:
        send_email_otp(payload.email, code, purpose="register")
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=f"Failed to send verification email: {e}")

    temp_token = _create_temp_token(str(user["id"]), purpose="mfa")
    log_audit(str(user["id"]), user["tier"], "register", f"New registration for {payload.email}", "success")

    return {
        "message": f"Verification code sent to {payload.email}. Enter it to complete registration.",
        "temp_token": temp_token,
    }


@app.post("/auth/login", tags=["Auth"])
async def login(payload: LoginRequest):
    """Step 1 of login: validate password + send email OTP."""
    user = get_user_by_email(payload.email)
    if not user or not verify_password(payload.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid email or password.")

    if not user["is_active"]:
        raise HTTPException(status_code=403, detail="Account is suspended. Contact support.")

    code = generate_otp()
    store_mfa_token(str(user["id"]), code, purpose="login")

    try:
        send_email_otp(payload.email, code, purpose="login")
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=f"Failed to send OTP: {e}")

    temp_token = _create_temp_token(str(user["id"]), purpose="mfa")
    log_audit(str(user["id"]), user["tier"], "login_attempt", f"OTP sent to {payload.email}", "success")

    return {
        "message": f"Verification code sent to {payload.email}.",
        "temp_token": temp_token,
        "mfa_required": True,
    }


@app.post("/auth/verify-mfa", response_model=TokenResponse, tags=["Auth"])
async def verify_mfa(payload: VerifyMFARequest):
    """Step 2: validate OTP, return access + refresh tokens."""
    user_id = _decode_temp_token(payload.temp_token)
    user = get_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=401, detail="User not found.")

    purpose = "register" if not user["is_verified"] else "login"

    try:
        verify_mfa_token(user_id, payload.code.strip(), purpose=purpose)
    except ValueError as e:
        log_audit(user_id, user["tier"], "mfa_verify", f"Failed OTP: {e}", "error")
        raise HTTPException(status_code=401, detail=str(e))

    # Mark verified on first login
    if not user["is_verified"]:
        mark_user_verified(user_id)
    else:
        update_last_login(user_id)

    # Issue tokens using user's database tier
    access_token = _create_access_token({
        "sub": user_id,
        "email": user["email"],
        "tier": user["tier"],
    })
    refresh_token = create_session(user_id)

    log_audit(user_id, user["tier"], "mfa_verify", f"MFA verified for {user['email']}", "success")

    expires_str = user["expires_at"].isoformat() if user.get("expires_at") else None

    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        user={
            "id": user_id,
            "email": user["email"],
            "mfa_method": user["mfa_method"],
            "is_verified": True,
            "tier": user["tier"],
            "expires_at": expires_str,
            "reg_ip": user.get("reg_ip"),
            "reg_country": user.get("reg_country"),
            "subscription_status": user["subscription_status"],
        },
    )


@app.post("/auth/resend-otp", tags=["Auth"])
async def resend_otp(payload: ResendOTPRequest):
    """Resend OTP — rate-limited to once per 60 seconds."""
    user_id = _decode_temp_token(payload.temp_token)
    user = get_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=401, detail="User not found.")

    purpose = "register" if not user["is_verified"] else "login"

    if not can_resend_otp(user_id, purpose=purpose):
        raise HTTPException(status_code=429, detail="Please wait 60 seconds before requesting a new code.")

    code = generate_otp()
    store_mfa_token(user_id, code, purpose=purpose)

    try:
        send_email_otp(user["email"], code, purpose=purpose)
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=f"Failed to resend OTP: {e}")

    return {"message": "A new verification code has been sent."}


@app.get("/auth/me", tags=["Auth"])
async def get_me(user: Dict[str, Any] = Depends(get_current_user)):
    """Returns the currently authenticated user's profile."""
    db_user = get_user_by_id(user["sub"])
    if not db_user:
        raise HTTPException(status_code=404, detail="User not found.")
    return {
        "id": str(db_user["id"]),
        "email": db_user["email"],
        "mfa_method": db_user["mfa_method"],
        "is_verified": db_user["is_verified"],
        "created_at": db_user["created_at"].isoformat() if db_user["created_at"] else None,
        "last_login_at": db_user["last_login_at"].isoformat() if db_user.get("last_login_at") else None,
    }


@app.post("/auth/logout", tags=["Auth"])
async def logout(request: Request, user: Dict[str, Any] = Depends(get_current_user)):
    """Revoke the refresh token session."""
    body = await request.json() if request.headers.get("content-type") == "application/json" else {}
    refresh_token = body.get("refresh_token", "")
    if refresh_token:
        revoke_session(refresh_token)
    log_audit(user["sub"], "free", "logout", f"User {user.get('email', 'unknown')} logged out", "success")
    return {"message": "Logged out successfully."}


# ─────────────────────────────────────────
# META ENDPOINTS
# ─────────────────────────────────────────
@app.get("/health", tags=["Meta"])
async def health_check():
    return {"status": "ok"}


@app.get("/v1/audit", tags=["Audit"])
async def get_audit_trail(user: Dict[str, Any] = Depends(get_current_user)):
    try:
        logs = get_audit_logs_pg(limit=100)
        # Serialize datetime objects
        for log in logs:
            for k, v in log.items():
                if hasattr(v, "isoformat"):
                    log[k] = v.isoformat()
        return logs
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch audit logs: {e}")


@app.post("/v1/chat", response_model=ChatResponse, tags=["Chat"])
async def chat_endpoint(payload: ChatRequest, user: Dict[str, Any] = Depends(get_current_user)):
    """Proxy natural language prompt + history to the LangChain agent."""
    if create_iceberg_agent is None:
        log_audit(
            user_id=user.get("sub", "unknown"),
            tier=user.get("tier", "trial"),
            action="chat_agent",
            details=f"Prompt: {payload.prompt} | Error: Agent runtime not available",
            status="error"
        )
        raise HTTPException(status_code=500, detail="Agent runtime not available (missing dependencies)")

    agent = create_iceberg_agent()

    # Convert messages list into LangChain chat history objects
    from langchain_core.messages import HumanMessage, AIMessage

    chat_history = []
    for m in payload.messages:
        role = m.get("role")
        content = m.get("content", "")
        if role == "user":
            chat_history.append(HumanMessage(content=content))
        else:
            chat_history.append(AIMessage(content=content))

    try:
        result = agent.invoke({"input": payload.prompt, "chat_history": chat_history})
        output_text: str = result.get("output", "") if isinstance(result, dict) else str(result)
        
        log_audit(
            user_id=user.get("sub", "unknown"),
            tier=user.get("tier", "trial"),
            action="chat_agent",
            details=f"Prompt: {payload.prompt}",
            status="success"
        )
    except Exception as err:
        log_audit(
            user_id=user.get("sub", "unknown"),
            tier=user.get("tier", "trial"),
            action="chat_agent",
            details=f"Prompt: {payload.prompt} | Error: {err}",
            status="error"
        )
        raise HTTPException(status_code=500, detail=f"Agent error: {err}")

    return ChatResponse(output=output_text)


@app.post("/v1/upload-csv", tags=["Ingestion"])
async def upload_csv_endpoint(
    file: UploadFile = File(...),
    user: Dict[str, Any] = Depends(get_current_user)
):
    temp_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
    os.makedirs(temp_dir, exist_ok=True)
    
    safe_filename = "".join([c for c in file.filename if c.isalnum() or c in (".", "_", "-")])
    temp_file_path = os.path.join(temp_dir, f"uploaded_{safe_filename}")
    
    try:
        with open(temp_file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
            
        df = pd.read_csv(temp_file_path)
        
        # Auto-detect schema
        type_map = {
            "int64": "integer", "int32": "integer",
            "float64": "double", "float32": "float",
            "bool": "boolean",
            "object": "string",
            "datetime64[ns]": "timestamp"
        }
        detected_schema = []
        for col in df.columns:
            dtype = str(df[col].dtype)
            iceberg_type = type_map.get(dtype, "string")
            detected_schema.append({"name": col, "type": iceberg_type})
            
        preview_rows = df.head(5).to_dict(orient="records")
        # Ensure values are serializable
        for row in preview_rows:
            for k, v in row.items():
                if pd.isna(v):
                    row[k] = None
                elif not isinstance(v, (str, int, float, bool, type(None))):
                    row[k] = str(v)
        
        log_audit(
            user_id=user.get("sub", "unknown"),
            tier=user.get("tier", "trial"),
            action="upload_csv",
            details=f"Uploaded {file.filename} ({len(df)} rows)",
            status="success"
        )
        
        return {
            "file_path": temp_file_path,
            "filename": file.filename,
            "row_count": len(df),
            "schema": detected_schema,
            "preview": preview_rows
        }
    except Exception as e:
        log_audit(
            user_id=user.get("sub", "unknown"),
            tier=user.get("tier", "trial"),
            action="upload_csv",
            details=f"Failed upload for {file.filename}: {e}",
            status="error"
        )
        raise HTTPException(status_code=500, detail=f"Failed to process CSV file: {e}")


@app.post("/v1/ingest", tags=["Ingestion"])
async def ingest_endpoint(
    payload: IngestRequest,
    user: Dict[str, Any] = Depends(get_current_user)
):
    from tools import create_iceberg_table, ingest_csv_to_iceberg
    
    schema_str = json.dumps(payload.schema_json)
    
    try:
        # 1. Create table
        create_res = create_iceberg_table.invoke({
            "namespace": payload.namespace,
            "table_name": payload.table_name,
            "schema_json": schema_str
        })
        
        if "error" in create_res.lower():
            raise Exception(f"Table creation error: {create_res}")
            
        # 2. Ingest CSV
        ingest_res = ingest_csv_to_iceberg.invoke({
            "namespace": payload.namespace,
            "table_name": payload.table_name,
            "csv_path": payload.file_path
        })
        
        if "error" in ingest_res.lower():
            raise Exception(f"Ingestion error: {ingest_res}")
            
        log_audit(
            user_id=user.get("sub", "unknown"),
            tier=user.get("tier", "trial"),
            action="ingest_data",
            details=f"Ingested table {payload.namespace}.{payload.table_name} ({payload.file_path})",
            status="success"
        )
        
        return {"status": "success", "message": f"Successfully created and ingested table {payload.namespace}.{payload.table_name}"}
        
    except Exception as e:
        log_audit(
            user_id=user.get("sub", "unknown"),
            tier=user.get("tier", "trial"),
            action="ingest_data",
            details=f"Failed ingestion for {payload.namespace}.{payload.table_name}: {e}",
            status="error"
        )
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/v1/config/aws", tags=["AWS Config"])
async def get_aws_config(user: Dict[str, Any] = Depends(get_current_user)):
    return {
        "region": os.environ.get("AWS_REGION", "eu-west-2"),
        "s3_warehouse_uri": os.environ.get("S3_WAREHOUSE_URI", ""),
        "access_key_id_set": bool(os.environ.get("AWS_ACCESS_KEY_ID")),
        "secret_access_key_set": bool(os.environ.get("AWS_SECRET_ACCESS_KEY")),
    }


@app.post("/v1/config/aws", tags=["AWS Config"])
async def update_aws_config(
    payload: AWSConfigRequest,
    user: Dict[str, Any] = Depends(get_current_user)
):
    os.environ["AWS_REGION"] = payload.region
    os.environ["S3_WAREHOUSE_URI"] = payload.s3_warehouse_uri
    
    if payload.access_key_id:
        os.environ["AWS_ACCESS_KEY_ID"] = payload.access_key_id
    if payload.secret_access_key:
        os.environ["AWS_SECRET_ACCESS_KEY"] = payload.secret_access_key
        
    log_audit(
        user_id=user.get("sub", "unknown"),
        tier=user.get("tier", "trial"),
        action="update_aws_config",
        details=f"AWS config updated: region={payload.region}, warehouse={payload.s3_warehouse_uri}",
        status="success"
    )
    return {"status": "success", "message": "AWS config updated successfully."}


@app.get("/v1/graph/stats", tags=["Graph"])
async def get_graph_stats_endpoint(
    graph_name: str = "pharma_graph",
    user: Dict[str, Any] = Depends(get_current_user)
):
    from graph_db import get_graph_stats
    stats = get_graph_stats(graph_name)
    if "error" in stats:
        log_audit(
            user_id=user.get("sub", "unknown"),
            tier=user.get("tier", "trial"),
            action="get_graph_stats",
            details=f"Failed to fetch graph stats: {stats['error']}",
            status="error"
        )
        raise HTTPException(status_code=500, detail=stats["error"])
        
    return stats


@app.post("/v1/graph/cypher", tags=["Graph"])
async def run_cypher_endpoint(
    payload: CypherRequest,
    user: Dict[str, Any] = Depends(get_current_user)
):
    from graph_db import execute_cypher_query
    try:
        df = execute_cypher_query(payload.graph_name, payload.query)
        
        log_audit(
            user_id=user.get("sub", "unknown"),
            tier=user.get("tier", "trial"),
            action="query_cypher",
            details=f"Graph: {payload.graph_name} | Query: {payload.query}",
            status="success"
        )
        
        if df.empty:
            return {"columns": [], "rows": []}
            
        columns = list(df.columns)
        rows = df.to_dict(orient="records")
        for r in rows:
            for k, v in r.items():
                if pd.isna(v):
                    r[k] = None
                elif not isinstance(v, (str, int, float, bool, type(None))):
                    r[k] = str(v)
        return {"columns": columns, "rows": rows}
    except Exception as e:
        log_audit(
            user_id=user.get("sub", "unknown"),
            tier=user.get("tier", "trial"),
            action="query_cypher",
            details=f"Failed Cypher on {payload.graph_name}: {e}",
            status="error"
        )
        raise HTTPException(status_code=500, detail=str(e))


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    return JSONResponse(status_code=exc.status_code, content={"error": exc.detail})
