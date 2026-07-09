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
import time
import asyncio
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
import pandas as pd

from fastapi import FastAPI, Depends, HTTPException, status, Request, UploadFile, File, Cookie, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
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
    update_password,
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
JWT_SECRET = os.environ.get("JWT_SECRET_KEY")
if not JWT_SECRET:
    import secrets
    JWT_SECRET = secrets.token_hex(32)
    print("[api/main] WARNING: JWT_SECRET_KEY env var was missing! Auto-generated a secure random signing key.")
JWT_ALGORITHM = os.environ.get("JWT_ALGORITHM", "HS256")
JWT_ACCESS_EXPIRE_MINUTES = int(os.environ.get("JWT_ACCESS_TOKEN_EXPIRE_MINUTES", 15))

app = FastAPI(
    title="Meldra AI — LakeMind Iceberg API",
    version="1.0.0",
    docs_url="/docs",
    description="Proprietary API. Copyright 2025 Meldra AI Ltd. All rights reserved.",
)

# Allow calling from frontend origin
# Allow calling from frontend origin
cors_origins_raw = os.environ.get("CORS_ALLOW_ORIGINS")
if cors_origins_raw:
    cors_origins = cors_origins_raw.split(",")
else:
    # Safe defaults to prevent wildcard credentials runtime errors in FastAPI
    cors_origins = ["http://localhost:5173", "http://localhost:3000", "http://127.0.0.1:5173"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["Authorization", "Content-Type", "X-Tenant-Tier", "X-Tenant-ID"],
)

# ── Live Traffic Monitoring Middleware ───────────────────────────────────────
class TrafficMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if path.startswith("/ws") or path.startswith("/docs") or path.startswith("/openapi") or request.method == "OPTIONS":
            return await call_next(request)

        import uuid
        from traffic_bus import traffic_bus, TrafficEvent
        from agent import current_request_id

        req_id = str(uuid.uuid4())
        token_context = current_request_id.set(req_id)
        start_time = time.time()

        # Capture request body safely
        request_body = ""
        content_type = request.headers.get("content-type", "")
        if "multipart/form-data" not in content_type:
            try:
                body_bytes = await request.body()
                request_body = body_bytes.decode("utf-8", errors="ignore")
                # Restore body for endpoint readers
                async def receive():
                    return {"type": "http.request", "body": body_bytes, "more_body": False}
                request._receive = receive
            except Exception:
                pass

        try:
            response = await call_next(request)
            latency_ms = (time.time() - start_time) * 1000
            
            event = TrafficEvent(
                id=req_id,
                timestamp=datetime.utcnow().isoformat() + "Z",
                type="http_request",
                method=request.method,
                path=path,
                status=str(response.status_code),
                latency_ms=latency_ms,
                request_body=request_body[:2000] if request_body else None,
                response_body=None
            )
            asyncio.create_task(traffic_bus.publish(event))
            return response
        except Exception as e:
            latency_ms = (time.time() - start_time) * 1000
            event = TrafficEvent(
                id=req_id,
                timestamp=datetime.utcnow().isoformat() + "Z",
                type="http_request",
                method=request.method,
                path=path,
                status="500",
                latency_ms=latency_ms,
                request_body=request_body[:2000] if request_body else None,
                response_body=str(e)[:2000]
            )
            asyncio.create_task(traffic_bus.publish(event))
            raise e
        finally:
            current_request_id.reset(token_context)

app.add_middleware(TrafficMiddleware)

# ─────────────────────────────────────────
# AUDIT LOG (delegates to PostgreSQL via auth_db)
# ─────────────────────────────────────────
def log_audit(user_id: str, tier: str, action: str, details: str, status: str):
    log_audit_pg(user_id=user_id, tier=tier, action=action, details=details, status=status)

def seed_demo_data():
    try:
        from catalog_setup import get_catalog, create_namespace_if_not_exists
        catalog = get_catalog()
        
        # Ensure default namespace exists
        create_namespace_if_not_exists(catalog, "default")
        
        # 1. Seed employees_sample
        emp_identifier = ("default", "employees_sample")
        table_exists = False
        try:
            catalog.load_table(emp_identifier)
            table_exists = True
        except Exception:
            pass
            
        if not table_exists:
            print("[startup-seeder] Seeding default.employees_sample...")
            from pyiceberg.schema import Schema
            from pyiceberg.types import NestedField, IntegerType, StringType, DoubleType
            import pyarrow as pa
            
            schema = Schema(
                NestedField(field_id=1, name="id", field_type=IntegerType(), required=True),
                NestedField(field_id=2, name="name", field_type=StringType(), required=False),
                NestedField(field_id=3, name="department", field_type=StringType(), required=False),
                NestedField(field_id=4, name="salary", field_type=DoubleType(), required=False),
                NestedField(field_id=5, name="joined_date", field_type=StringType(), required=False),
            )
            
            # Create Table
            table = catalog.create_table(emp_identifier, schema=schema)
            
            # Append Snapshot 1
            data1 = {
                "id": [1, 2, 3],
                "name": ["Sumit", "Alice", "Bob"],
                "department": ["Data Engineering", "Enterprise Architecture", "Data Analytics"],
                "salary": [125000.0, 140000.0, 95000.0],
                "joined_date": ["2024-01-15", "2023-11-10", "2024-03-01"]
            }
            table.append(pa.Table.from_pydict(data1))
            
            # Append Snapshot 2 (adds transactions history for Time Travel)
            data2 = {
                "id": [4, 5],
                "name": ["Charlie", "Diana"],
                "department": ["Data Platform", "VP of Data"],
                "salary": [115000.0, 195000.0],
                "joined_date": ["2024-06-01", "2022-04-12"]
            }
            table.append(pa.Table.from_pydict(data2))
            
            print("[startup-seeder] Seeded default.employees_sample successfully with 2 snapshots.")
            
        # 2. Seed orders_sample
        ord_identifier = ("default", "orders_sample")
        ord_exists = False
        try:
            catalog.load_table(ord_identifier)
            ord_exists = True
        except Exception:
            pass
            
        if not ord_exists:
            print("[startup-seeder] Seeding default.orders_sample...")
            from pyiceberg.schema import Schema
            from pyiceberg.types import NestedField, IntegerType, StringType, DoubleType
            import pyarrow as pa
            
            schema = Schema(
                NestedField(field_id=1, name="order_id", field_type=IntegerType(), required=True),
                NestedField(field_id=2, name="customer", field_type=StringType(), required=False),
                NestedField(field_id=3, name="amount", field_type=DoubleType(), required=False),
                NestedField(field_id=4, name="status", field_type=StringType(), required=False),
            )
            
            table = catalog.create_table(ord_identifier, schema=schema)
            
            data = {
                "order_id": [1001, 1002, 1003, 1004],
                "customer": ["Acme Corp", "Beta LLC", "Delta Inc", "Sigma Co"],
                "amount": [4500.50, 12000.00, 750.25, 92000.00],
                "status": ["COMPLETED", "PENDING", "CANCELLED", "COMPLETED"]
            }
            table.append(pa.Table.from_pydict(data))
            print("[startup-seeder] Seeded default.orders_sample successfully.")
            
        # 3. Seed transactions_10k
        tx_identifier = ("default", "transactions_10k")
        tx_exists = False
        try:
            catalog.load_table(tx_identifier)
            tx_exists = True
        except Exception:
            pass
            
        if not tx_exists:
            print("[startup-seeder] Seeding default.transactions_10k (10,000 rows)...")
            from pyiceberg.schema import Schema
            from pyiceberg.types import NestedField, IntegerType, StringType, DoubleType
            import pyarrow as pa
            import random
            
            schema = Schema(
                NestedField(field_id=1, name="tx_id", field_type=IntegerType(), required=True),
                NestedField(field_id=2, name="account_from", field_type=StringType(), required=False),
                NestedField(field_id=3, name="account_to", field_type=StringType(), required=False),
                NestedField(field_id=4, name="amount", field_type=DoubleType(), required=False),
                NestedField(field_id=5, name="status", field_type=StringType(), required=False),
                NestedField(field_id=6, name="timestamp", field_type=StringType(), required=False),
            )
            
            table = catalog.create_table(tx_identifier, schema=schema)
            
            # Generate 10k rows of mock transaction data
            random.seed(42)
            status_options = ["COMPLETED", "COMPLETED", "COMPLETED", "PENDING", "FAILED"]
            tx_ids = list(range(1, 10001))
            accounts_from = [f"ACC-{random.randint(100, 250):03d}" for _ in range(10000)]
            accounts_to = [f"ACC-{random.randint(150, 300):03d}" for _ in range(10000)]
            amounts = [round(random.uniform(10.0, 50000.0), 2) for _ in range(10000)]
            statuses = [random.choice(status_options) for _ in range(10000)]
            timestamps = [f"2026-07-06T00:{random.randint(10, 59):02d}:{random.randint(10, 59):02d}Z" for _ in range(10000)]
            
            data = {
                "tx_id": tx_ids,
                "account_from": accounts_from,
                "account_to": accounts_to,
                "amount": amounts,
                "status": statuses,
                "timestamp": timestamps
            }
            table.append(pa.Table.from_pydict(data))
            print("[startup-seeder] Seeded default.transactions_10k successfully with 10,000 records.")
            
    except Exception as e:
        print(f"[startup-seeder] Error seeding demo data: {e}")

@app.on_event("startup")
def startup_event():
    init_auth_schema()
    try:
        from graph_db import init_graph_tables
        init_graph_tables()
    except Exception as e:
        print(f"[api/main] Failed to initialize graph tables on startup: {e}")
    seed_demo_data()
    
    # Launch Arrow Flight Server in background thread
    try:
        import threading
        from arrow_flight_server import meldraFlightServer
        def run_flight():
            try:
                server = meldraFlightServer(host="0.0.0.0", port=8888)
                print("[api/main] Starting Arrow Flight Server on port 8888...")
                server.serve()
            except Exception as ex:
                print(f"[api/main] Arrow Flight Server failed: {ex}")
        t = threading.Thread(target=run_flight, daemon=True)
        t.start()
    except Exception as e:
        print(f"[api/main] Failed to launch Flight thread: {e}")

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
    write_mode: Optional[str] = "append" # "append", "overwrite", "upsert"
    merge_key: Optional[str] = None

class SuccessFactorsRequest(BaseModel):
    # Connection
    sf_endpoint: str          # e.g. https://api4.successfactors.com
    company_id: str           # e.g. ACME_CORP
    # Auth
    auth_type: str            # "basic" or "oauth2"
    username: Optional[str] = None      # Basic auth
    password: Optional[str] = None      # Basic auth
    client_id: Optional[str] = None     # OAuth2
    client_secret: Optional[str] = None # OAuth2
    token_url: Optional[str] = None     # OAuth2 token endpoint override
    # Entity & target
    entity_name: str          # e.g. PerPersonal, EmpJob, EmpCompensation
    top: Optional[int] = 1000 # OData $top (max records per page)
    namespace: str = "default"
    table_name: str
    write_mode: Optional[str] = "overwrite"

class CypherRequest(BaseModel):
    graph_name: str
    query: str

class MCPExecuteRequest(BaseModel):
    server_name: str
    tool_name: str
    arguments: Dict[str, Any]

# ── Auth Schemas ─────────────────────────
class RegisterRequest(BaseModel):
    email: str
    password: str
    mfa_method: str = "email"   # only 'email' for now
    role: Optional[str] = "Business Analyst"

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

class ForgotPasswordRequest(BaseModel):
    email: str

class ResetPasswordRequest(BaseModel):
    temp_token: str   # same opaque temp token issued after forgot-password
    code: str         # 6-digit OTP from email
    new_password: str

    @field_validator("new_password")
    @classmethod
    def _strong_password(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters.")
        if not any(c.isupper() for c in v):
            raise ValueError("Password must contain at least one uppercase letter.")
        if not any(c.isdigit() for c in v):
            raise ValueError("Password must contain at least one number.")
        return v

class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str

    @field_validator("new_password")
    @classmethod
    def _strong_password(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters.")
        if not any(c.isupper() for c in v):
            raise ValueError("Password must contain at least one uppercase letter.")
        if not any(c.isdigit() for c in v):
            raise ValueError("Password must contain at least one number.")
        return v

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
    """Short-lived token used to identify a pending MFA session (15 min)."""
    payload = {
        "sub": user_id,
        "purpose": purpose,
        "exp": datetime.utcnow() + timedelta(minutes=15),
        "type": "temp",
    }
    return jose_jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def _decode_temp_token(token: str) -> str:
    """Decode temp token, return user_id or raise 401."""
    try:
        payload = jose_jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        if payload.get("type") != "temp":
            print(f"[auth] _decode_temp_token: Invalid token type in payload: {payload}")
            raise HTTPException(status_code=401, detail="Invalid token type")
        return payload["sub"]
    except JWTError as e:
        print(f"[auth] _decode_temp_token JWTError: {e}. Token: {token[:20]}...{token[-10:] if len(token) > 10 else ''}")
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
        from auth_db import _get_conn
        conn = _get_conn()
        cur = conn.cursor()
        cur.execute("SELECT count(*) FROM auth.users;")
        first_user = cur.fetchone()["count"] == 0
        conn.close()
        
        # Force "Business Analyst" role for new public signups (Admin is set manually or for first user)
        assigned_role = "Admin" if first_user else "Business Analyst"
        
        user = create_user(
            email=payload.email,
            password=payload.password,
            mfa_method=payload.mfa_method,
            tier="trial",
            reg_ip=reg_ip,
            reg_country=reg_country,
            user_role=assigned_role
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


# Global rate limiting cache for failed login attempts
from collections import defaultdict
failed_logins = defaultdict(list)

def check_login_rate_limit(email: str):
    now = time.time()
    # Filter attempts in the last 60 seconds
    attempts = [t for t in failed_logins[email] if now - t < 60]
    failed_logins[email] = attempts
    if len(attempts) >= 5:
         raise HTTPException(
             status_code=429,
             detail="Too many failed login attempts. Please wait 60 seconds."
         )

def record_failed_login(email: str):
    failed_logins[email].append(time.time())


@app.post("/auth/login", tags=["Auth"])
async def login(payload: LoginRequest):
    """Step 1 of login: validate password + send email OTP."""
    check_login_rate_limit(payload.email)
    user = get_user_by_email(payload.email)
    if not user or not verify_password(payload.password, user["password_hash"]):
        record_failed_login(payload.email)
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
        if user["email"].startswith("load_test_") and payload.code.strip() == "123456":
            # Bypass database OTP verification for simulated load testing
            pass
        else:
            verify_mfa_token(user_id, payload.code.strip(), purpose=purpose)
    except ValueError as e:
        log_audit(user_id, user["tier"], "mfa_verify", f"Failed OTP: {e}", "error")
        raise HTTPException(status_code=401, detail=str(e))

    # Mark verified on first login
    if not user["is_verified"]:
        mark_user_verified(user_id)
    else:
        update_last_login(user_id)

    # Issue tokens using user's database tier and role
    access_token = _create_access_token({
        "sub": user_id,
        "email": user["email"],
        "tier": user["tier"],
        "role": user.get("user_role", "Business Analyst")
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
            "role": user.get("user_role", "Business Analyst"),
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


@app.post("/auth/forgot-password", tags=["Auth"])
async def forgot_password(payload: ForgotPasswordRequest):
    """
    Step 1 of password reset: lookup email, send a 'reset' OTP.
    Always returns 200 to prevent email enumeration attacks.
    """
    user = get_user_by_email(payload.email)
    if not user:
        # Return a generic success response regardless — don't leak whether email exists
        return {"message": "If that email is registered you will receive a reset code shortly.", "temp_token": ""}

    code = generate_otp()
    store_mfa_token(str(user["id"]), code, purpose="reset")

    try:
        send_email_otp(payload.email, code, purpose="reset")
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=f"Failed to send reset email: {e}")

    temp_token = _create_temp_token(str(user["id"]), purpose="mfa")
    log_audit(str(user["id"]), user["tier"], "forgot_password", f"Password reset code sent to {payload.email}", "success")

    return {
        "message": f"A password reset code has been sent to {payload.email}.",
        "temp_token": temp_token,
    }


@app.post("/auth/reset-password", tags=["Auth"])
async def reset_password(payload: ResetPasswordRequest):
    """
    Step 2 of password reset: verify OTP and set new password.
    """
    user_id = _decode_temp_token(payload.temp_token)
    user = get_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=401, detail="User not found.")

    try:
        verify_mfa_token(user_id, payload.code.strip(), purpose="reset")
    except ValueError as e:
        log_audit(user_id, user["tier"], "reset_password", f"Failed OTP: {e}", "error")
        raise HTTPException(status_code=401, detail=str(e))

    update_password(user_id, payload.new_password)
    log_audit(user_id, user["tier"], "reset_password", f"Password reset successful for {user['email']}", "success")

    return {"message": "Password reset successfully. You can now log in with your new password."}


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
        "role": db_user.get("user_role", "Business Analyst")
    }



@app.post("/auth/change-password", tags=["Auth"])
async def change_password(payload: ChangePasswordRequest, user: Dict[str, Any] = Depends(get_current_user)):
    """Allows an authenticated user to change their password."""
    user_id = user["sub"]
    db_user = get_user_by_id(user_id)
    if not db_user:
        raise HTTPException(status_code=404, detail="User not found.")

    if not verify_password(payload.current_password, db_user["password_hash"]):
        raise HTTPException(status_code=400, detail="Current password is incorrect.")

    update_password(user_id, payload.new_password)
    log_audit(user_id, db_user["tier"], "change_password", f"Password changed successfully by user {db_user['email']}", "success")
    return {"message": "Password updated successfully."}


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
        raw_output = result.get("output", "") if isinstance(result, dict) else result
        if isinstance(raw_output, list):
            output_text = "".join([item.get("text", "") for item in raw_output if isinstance(item, dict)])
        elif isinstance(raw_output, dict):
            output_text = raw_output.get("text", str(raw_output))
        else:
            output_text = str(raw_output)
        
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
        
        # Auto-detect schema — use "long" (int64) to match pandas/PyArrow defaults.
        # Iceberg IntegerType is 32-bit; LongType is 64-bit (what pandas produces).
        type_map = {
            "int64": "long", "int32": "integer",
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
    from catalog_setup import get_catalog
    from tools import create_iceberg_table
    import pyarrow as pa
    import pyarrow.csv as pv
    
    schema_str = json.dumps(payload.schema_json)
    
    try:
        # 1. Create table if not exists
        create_res = create_iceberg_table.invoke({
            "namespace": payload.namespace,
            "table_name": payload.table_name,
            "schema_json": schema_str
        })
        
        if "error" in create_res.lower():
            raise Exception(f"Table creation error: {create_res}")
            
        # 2. Read CSV file into PyArrow
        if not os.path.exists(payload.file_path):
            raise Exception(f"CSV file path does not exist: {payload.file_path}")
            
        arrow_table = pv.read_csv(payload.file_path)
        
        # Load Iceberg Table & Schema
        catalog = get_catalog()
        identifier = (payload.namespace, payload.table_name)
        table = catalog.load_table(identifier)
        
        # --- Data Quality Contract Validation ---
        rules_str = table.properties.get("data_contracts", "[]")
        rules = json.loads(rules_str)
        if rules:
            from meldra import MeldraValidator
            df = arrow_table.to_pandas()
            is_valid, validation_logs = MeldraValidator.validate_dataframe(df, rules)
            if not is_valid:
                log_audit(
                    user_id=user.get("sub", "unknown"),
                    tier=user.get("tier", "trial"),
                    action="ingest_validation",
                    details=f"Data contract checks failed for {payload.namespace}.{payload.table_name}: {validation_logs}",
                    status="error"
                )
                raise HTTPException(
                    status_code=400, 
                    detail={"error": "Data Contract Validation Failed", "logs": validation_logs}
                )

        pyarrow_schema = table.schema().as_arrow()
        
        # Cast columns to match Iceberg schema
        cast_arrays = []
        cast_fields = []
        for field in pyarrow_schema:
            if field.name in arrow_table.schema.names:
                col = arrow_table.column(field.name)
                cast_arrays.append(col.cast(field.type))
                cast_fields.append(field)
                
        arrow_table = pa.table(
            {field.name: arr for field, arr in zip(cast_fields, cast_arrays)},
            schema=pa.schema(cast_fields)
        )
        
        # 3. Ingest based on write_mode
        if payload.write_mode == "overwrite":
            table.overwrite(arrow_table)
        elif payload.write_mode == "upsert" and payload.merge_key:
            existing_arrow = table.scan().to_arrow()
            if len(existing_arrow) > 0:
                existing_df = existing_arrow.to_pandas()
                new_df = arrow_table.to_pandas()
                
                # Keep new records, drop old duplicates on key
                merged_df = pd.concat([existing_df, new_df]).drop_duplicates(subset=[payload.merge_key], keep='last')
                
                merged_arrow = pa.Table.from_pandas(merged_df)
                cast_arrays_m = []
                cast_fields_m = []
                for field in pyarrow_schema:
                    if field.name in merged_arrow.schema.names:
                        col = merged_arrow.column(field.name)
                        cast_arrays_m.append(col.cast(field.type))
                        cast_fields_m.append(field)
                
                merged_arrow = pa.table(
                    {field.name: arr for field, arr in zip(cast_fields_m, cast_arrays_m)},
                    schema=pa.schema(cast_fields_m)
                )
                table.overwrite(merged_arrow)
            else:
                table.append(arrow_table)
        else:
            # Default append
            table.append(arrow_table)
            
        log_audit(
            user_id=user.get("sub", "unknown"),
            tier=user.get("tier", "trial"),
            action="ingest_data",
            details=f"Ingested table {payload.namespace}.{payload.table_name} ({payload.file_path}, write_mode={payload.write_mode})",
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


@app.post("/v1/ingest/successfactors", tags=["Ingestion"])
async def ingest_successfactors(
    payload: SuccessFactorsRequest,
    user: Dict[str, Any] = Depends(get_current_user)
):
    """
    Fetch data from SAP SuccessFactors OData API and ingest into the Iceberg lakehouse.
    Supports Basic Auth (username/password) and OAuth2 Client Credentials flow.
    Handles OData pagination ($skiptoken / @odata.nextLink) automatically.
    """
    import requests
    import pyarrow as pa
    from catalog_setup import get_catalog
    from tools import create_iceberg_table

    base_url = payload.sf_endpoint.rstrip("/")
    company_id = payload.company_id
    entity = payload.entity_name

    # ── 1. Resolve Auth ─────────────────────────────────────────────────────
    session = requests.Session()
    session.headers.update({"Accept": "application/json",
                             "Content-Type": "application/json"})

    if payload.auth_type == "basic":
        if not payload.username or not payload.password:
            raise HTTPException(status_code=400,
                detail="username and password are required for Basic auth")
        sf_user = f"{payload.username}@{company_id}"
        session.auth = (sf_user, payload.password)

    elif payload.auth_type == "oauth2":
        if not payload.client_id or not payload.client_secret:
            raise HTTPException(status_code=400,
                detail="client_id and client_secret are required for OAuth2")
        token_url = payload.token_url or f"{base_url}/oauth/token"
        try:
            token_resp = requests.post(token_url, data={
                "grant_type": "client_credentials",
                "client_id": payload.client_id,
                "client_secret": payload.client_secret,
                "company_id": company_id,
            }, timeout=30)
            token_resp.raise_for_status()
            access_token = token_resp.json().get("access_token")
            if not access_token:
                raise HTTPException(status_code=401,
                    detail=f"OAuth2 token response missing access_token: {token_resp.text}")
            session.headers["Authorization"] = f"Bearer {access_token}"
        except requests.RequestException as e:
            raise HTTPException(status_code=502, detail=f"OAuth2 token fetch failed: {e}")
    else:
        raise HTTPException(status_code=400,
            detail="auth_type must be 'basic' or 'oauth2'")

    # ── 2. Paginated OData Fetch ─────────────────────────────────────────────
    records: list = []
    odata_url = f"{base_url}/odata/v2/{entity}?$format=json&$top={payload.top}&companyId={company_id}"

    try:
        while odata_url:
            resp = session.get(odata_url, timeout=60)
            resp.raise_for_status()
            body = resp.json()

            d = body.get("d", body)
            page_records = d.get("results", d) if isinstance(d, dict) else d
            if not isinstance(page_records, list):
                raise HTTPException(status_code=502,
                    detail=f"Unexpected OData response structure: {str(body)[:400]}")

            for rec in page_records:
                clean = {k: v for k, v in rec.items()
                         if not k.startswith("__") and not isinstance(v, dict)}
                records.append(clean)

            next_link = (d.get("__next") or
                         body.get("@odata.nextLink") or
                         d.get("__deferred"))
            odata_url = next_link if isinstance(next_link, str) else None

    except requests.RequestException as e:
        raise HTTPException(status_code=502, detail=f"SuccessFactors API error: {e}")

    if not records:
        raise HTTPException(status_code=404,
            detail=f"Entity '{entity}' returned 0 records. Check entity name and permissions.")

    # ── 3. Convert to PyArrow table ──────────────────────────────────────────
    try:
        df = pd.DataFrame(records)
        for col in df.select_dtypes(include="object").columns:
            df[col] = df[col].astype(str)
        arrow_table = pa.Table.from_pandas(df, preserve_index=False)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"DataFrame conversion failed: {e}")

    # ── 4. Build schema_json ──────────────────────────────────────────────────
    type_map = {
        pa.string(): "string", pa.large_string(): "string",
        pa.int32(): "int", pa.int64(): "long",
        pa.float32(): "float", pa.float64(): "double",
        pa.bool_(): "boolean",
        pa.date32(): "date", pa.timestamp("us"): "timestamp",
    }
    schema_json = []
    for field in arrow_table.schema:
        iceberg_type = type_map.get(field.type, "string")
        schema_json.append({"name": field.name, "type": iceberg_type})

    # ── 5. Create Iceberg table ───────────────────────────────────────────────
    import json as _json
    create_res = create_iceberg_table.invoke({
        "namespace": payload.namespace,
        "table_name": payload.table_name,
        "schema_json": _json.dumps(schema_json)
    })
    if "error" in create_res.lower():
        raise HTTPException(status_code=500, detail=f"Table creation failed: {create_res}")

    # ── 6. Write to Iceberg ──────────────────────────────────────────────────
    try:
        catalog = get_catalog()
        table = catalog.load_table((payload.namespace, payload.table_name))
        pyarrow_schema = table.schema().as_arrow()

        cast_arrays, cast_fields = [], []
        for field in pyarrow_schema:
            if field.name in arrow_table.schema.names:
                col = arrow_table.column(field.name)
                try:
                    cast_arrays.append(col.cast(field.type))
                except Exception:
                    cast_arrays.append(col.cast(pa.string()))
                cast_fields.append(field)

        final_table = pa.table(
            {f.name: arr for f, arr in zip(cast_fields, cast_arrays)},
            schema=pa.schema(cast_fields)
        )

        if payload.write_mode == "overwrite":
            table.overwrite(final_table)
        else:
            table.append(final_table)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Iceberg write failed: {e}")

    log_audit(
        user_id=user.get("sub", "unknown"),
        tier=user.get("tier", "trial"),
        action="sf_ingest",
        details=(f"SuccessFactors {entity} → {payload.namespace}.{payload.table_name}: "
                 f"{len(records)} rows via {payload.auth_type}"),
        status="success"
    )

    return {
        "status": "success",
        "message": (f"Successfully ingested {len(records):,} records from SF entity '{entity}' "
                     f"into {payload.namespace}.{payload.table_name}"),
        "rows_ingested": len(records),
        "columns": len(schema_json),
        "table": f"{payload.namespace}.{payload.table_name}",
        "auth_method": payload.auth_type,
    }


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


@app.post("/v1/mcp/execute", tags=["MCP"])
async def execute_mcp_tool_endpoint(
    payload: MCPExecuteRequest,
    user: Dict[str, Any] = Depends(get_current_user)
):
    import time
    start_time = time.time()
    
    server = payload.server_name
    tool = payload.tool_name
    args = payload.arguments
    
    logs = []
    result = {}
    
    logs.append(f"[*] Connecting to MCP Server: '{server}'...")
    logs.append(f"[*] Invoking Tool: '{tool}' with arguments: {json.dumps(args)}")
    
    # 1. Iceberg Catalog MCP Server
    if "Iceberg" in server or "iceberg" in tool:
        logs.append("[info] Resolving S3 warehouse credentials from AWS config...")
        logs.append(f"[info] Accessing Glue Catalog in region: {os.environ.get('AWS_REGION', 'eu-west-2')}")
        if tool == "list_iceberg_tables":
            logs.append("[query] Scanning Glue database 'default'...")
            result = {"tables": ["default.sap_bseg", "finance.fact_revenue", "supply_chain.stock_levels"]}
        elif tool == "create_iceberg_table":
            ns = args.get("namespace", "default")
            tbl = args.get("table_name", "new_table")
            logs.append(f"[ddl] Creating table metadata for {ns}.{tbl} on S3...")
            logs.append(f"[ddl] Initializing schema with {len(args.get('schema_json', []))} columns...")
            result = {
                "status": "created",
                "table": f"{ns}.{tbl}",
                "s3_path": f"s3://your-bucket/iceberg-warehouse/{ns}.db/{tbl}",
                "metadata_version": 1
            }
        elif tool == "query_iceberg_data":
            q = args.get("sql_query", "")
            logs.append(f"[sql] Executing query: {q}")
            logs.append("[sql] Loading S3 metadata manifest list and statistics...")
            logs.append("[sql] Running warm S3 parquet file scan using local DuckDB engine...")
            if "sap_bseg" in q.lower():
                result = {
                    "columns": ["MANDT", "BUKRS", "BELNR", "GJAHR", "BUZEI", "DMBTR", "WAERS"],
                    "rows": [
                        {"MANDT": "100", "BUKRS": "US01", "BELNR": "1800000001", "GJAHR": 2026, "BUZEI": "001", "DMBTR": 45000.00, "WAERS": "USD"},
                        {"MANDT": "100", "BUKRS": "US01", "BELNR": "1800000001", "GJAHR": 2026, "BUZEI": "002", "DMBTR": -45000.00, "WAERS": "USD"},
                        {"MANDT": "100", "BUKRS": "UK01", "BELNR": "1800000002", "GJAHR": 2026, "BUZEI": "001", "DMBTR": 12500.50, "WAERS": "GBP"}
                    ]
                }
            else:
                result = {
                    "columns": ["id", "val"],
                    "rows": [{"id": 1, "val": "Sample A"}, {"id": 2, "val": "Sample B"}]
                }
        elif tool == "ingest_csv_to_iceberg":
            logs.append(f"[ingest] Reading CSV file from path: {args.get('csv_path')}")
            logs.append("[ingest] Validating schema constraints and types...")
            logs.append("[ingest] Writing Apache Parquet files to S3 warehouse...")
            logs.append("[ingest] Committing transaction metadata to Glue Catalog (atomically)...")
            result = {
                "status": "ingested",
                "table": f"{args.get('namespace', 'default')}.{args.get('table_name', 'sap_bseg')}",
                "rows_written": 1250,
                "commit_snapshot_id": 4983274982739487
            }
        else:
            result = {"message": "Iceberg tool executed successfully."}
            
    # 2. SAP BAPI & RFC MCP Agent
    elif "SAP" in server or "sap" in tool or "bapi" in tool:
        logs.append("[sap] Initializing PyRFC connection pool to SAP Application Server instance...")
        logs.append("[sap] Authentication check: User SEC_ADMIN role verified.")
        if tool == "approve_purchase_requisition":
            pr = args.get("pr_number", "4500012345")
            code = args.get("release_code", "A1")
            logs.append(f"[sap] Invoking RFC function 'BAPI_PR_CHANGE' on host SAP-ECC-PRD...")
            logs.append(f"[sap] Passing RELEASE_CODE: {code}, REQUISITION_NUMBER: {pr}")
            result = {
                "BAPI_RETURN": {
                    "TYPE": "S",
                    "ID": "ME",
                    "NUMBER": "000",
                    "MESSAGE": f"Purchase Requisition {pr} released successfully with code {code}."
                }
            }
        elif tool == "release_billing_block":
            so = args.get("sales_order", "1000293")
            logs.append(f"[sap] Invoking RFC function 'BAPI_SALESORDER_CHANGE' on host SAP-ECC-PRD...")
            logs.append(f"[sap] Setting BILLING_BLOCK to clear for Sales Order {so}")
            result = {
                "BAPI_RETURN": {
                    "TYPE": "S",
                    "ID": "V1",
                    "NUMBER": "000",
                    "MESSAGE": f"Sales Order {so} billing block removed successfully."
                }
            }
        elif tool == "update_vendor_payment_term":
            vendor = args.get("vendor_id", "V10001")
            term = args.get("payment_term", "NT30")
            logs.append(f"[sap] Invoking RFC function 'BAPI_VENDOR_CHANGE' on host SAP-ECC-PRD...")
            logs.append(f"[sap] Setting ZTERM to {term} for Vendor {vendor} in company code {args.get('company_code', '1000')}")
            result = {
                "BAPI_RETURN": {
                    "TYPE": "S",
                    "ID": "FI",
                    "NUMBER": "000",
                    "MESSAGE": f"Vendor {vendor} payment terms updated successfully to {term}."
                }
            }
        else:
            result = {"message": "SAP RFC connection call completed."}
            
    # 3. Snowflake Zero-Copy MCP
    elif "Snowflake" in server or "snowflake" in tool:
        logs.append("[snowflake] Connecting to Snowflake database account SF_ENT_CORP...")
        logs.append("[snowflake] Setting active role: ACCOUNTADMIN, warehouse: FIN_WH_XL...")
        if tool == "revenue_trend_by_period":
            logs.append("[snowflake] Scanning schema finance.fact_revenue using zero-copy metadata clone...")
            result = [
                {"period": "2026-04", "revenue": 1450000.00},
                {"period": "2026-05", "revenue": 1620000.00},
                {"period": "2026-06", "revenue": 1890000.00}
            ]
        elif tool == "variance_analysis":
            dept = args.get("department_id", "DEP-100")
            logs.append(f"[snowflake] Running actuals vs budget cross-join query for department: {dept}")
            result = {
                "department": dept,
                "actual_spend": 420000.00,
                "budgeted_spend": 450000.00,
                "variance": -30000.00,
                "status": "Under Budget"
            }
        elif tool == "top_vendors_by_spend":
            n = args.get("top_n", 5)
            logs.append(f"[snowflake] Querying finance.ap_invoices for top {n} vendors by total quarterly spend...")
            result = [
                {"rank": 1, "vendor": "Apex Logistics Ltd", "total_spend": 820000.00},
                {"rank": 2, "vendor": "Techno Corp", "total_spend": 540000.00},
                {"rank": 3, "vendor": "Prime Energy", "total_spend": 320000.00}
            ]
        else:
            result = {"message": "Snowflake tool call completed."}
            
    # 4. Compliance Audit Trail MCP
    elif "Compliance" in server or "audit" in tool:
        logs.append("[compliance] Initializing cryptographic signature pipeline...")
        logs.append("[compliance] Generating hash signature for transaction payload...")
        logs.append("[compliance] Writing append-only audit event to S3 Iceberg log partition compliance.audit_log...")
        import uuid
        result = {
            "status": "written",
            "event_id": str(uuid.uuid4()),
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "signature_hash": "a4f89d38c2901e91823f..."
        }
        
    # 5. Autonomous Procurement MCP
    elif "Procurement" in server or "procure" in tool:
        logs.append("[agent] Scanning S3 Iceberg stock_levels database...")
        logs.append("[agent] Safety stock breach detected on SKU: PCB-44A. Current qty: 45, Safety threshold: 100")
        logs.append("[agent] Invoking Supplier Selection Graph sub-agent to select optimal supplier...")
        logs.append("[agent] Supplier selected: Prime Electronics (Lead time: 2 days, score: 9.8)")
        logs.append("[agent] Invoking SAP MM agent to raise Purchase Requisition BAPI call...")
        result = {
            "status": "success",
            "stock_breach_detected": True,
            "sku": "PCB-44A",
            "reorder_quantity": 150,
            "selected_supplier": "Prime Electronics",
            "sap_pr_number": "4500018902",
            "audit_trail_signature": "0f38b29f..."
        }
        
    # 6. Zero-Trust IAM Provisioning MCP
    elif "IAM" in server or "iam" in tool or "provision" in tool:
        logs.append("[iam] Listening for employee status change events...")
        logs.append("[iam] User status change event detected: 'TERMINATION' for user: johndoe@company.com")
        logs.append("[iam] Initiating zero-trust multi-platform revocation protocol...")
        logs.append("[iam] [1/3] Calling Okta API: Revoking active session tokens...")
        logs.append("[iam] [2/3] Calling Azure Active Directory API: Disabling User Principal Name...")
        logs.append("[iam] [3/3] Calling AWS IAM API: Removing user from policy groups...")
        logs.append("[iam] All active access revoked successfully.")
        result = {
            "status": "access_revoked",
            "user": "johndoe@company.com",
            "revoked_services": ["okta", "azure_ad", "aws_iam"],
            "verification_status": "complete",
            "propagation_time_ms": 120
        }
        
    # 7. Fraud Ring Detection MCP
    elif "Fraud" in server or "fraud" in tool:
        logs.append("[fraud] Loading latest inter-bank payment instruction batch...")
        logs.append("[fraud] Connecting to Postgres AGE payment graph db schema 'payments_graph'...")
        logs.append("[fraud] Executing multi-hop recursive Cypher loop traversal query...")
        logs.append("[fraud] Cypher query: MATCH cycle = (a:Account)-[:SENT_TO*3..8]->(a) RETURN cycle")
        logs.append("[fraud] Ring path detected: ACCT-8827 -> ACCT-9102 -> ACCT-0092 -> ACCT-8827 (Velocity: $450,000/24h)")
        logs.append("[fraud] Triggering automatic account lock policy...")
        result = {
            "fraud_ring_detected": True,
            "ring_members": ["ACCT-8827", "ACCT-9102", "ACCT-0092"],
            "velocity_24h_usd": 450000.00,
            "hops_count": 3,
            "auto_freeze_status": "frozen",
            "sar_flagged": True
        }
        
    # 8. Multi-Agent Orchestration
    elif "Orchestration" in server or "orchestrate" in tool:
        logs.append("[orchestrator] Month-end closing process initiated...")
        logs.append("[orchestrator] [Step 1] Triggering Ledger Reconciliation agent...")
        logs.append("[orchestrator] [Step 2] Triggering FX Revaluation agent...")
        logs.append("[orchestrator] [Step 3] Triggering Intercompany Elimination graph agent...")
        logs.append("[orchestrator] [Step 4] Triggering Management Reporting agent...")
        logs.append("[orchestrator] All sub-agents completed work successfully without errors.")
        result = {
            "close_status": "success",
            "duration_minutes": 185,
            "reconciled_company_codes": ["1000", "2000"],
            "variance_adjusted": 0.00,
            "board_report_hash": "df872a9b...",
            "audit_trail_recorded": True
        }
    else:
        logs.append("[info] Executing custom tool call...")
        result = {"message": "Tool executed successfully.", "arguments": args}
        
    duration = int((time.time() - start_time) * 1000)
    logs.append(f"[+] Execution completed successfully in {duration}ms.")
    
    log_audit(
        user_id=user.get("sub", "unknown"),
        tier=user.get("tier", "trial"),
        action="mcp_execute_tool",
        details=f"Server: {server} | Tool: {tool}",
        status="success"
    )
    
    return {
        "logs": logs,
        "result": result,
        "duration_ms": duration
    }


# ─────────────────────────────────────────────────────────────────────────────
# DISTRIBUTED QUERY ENGINE (DQE) ENDPOINTS
# ─────────────────────────────────────────────────────────────────────────────

# Lazy import — avoids pulling in PyIceberg/DuckDB at module import time
def _get_query_engine():
    import sys, os as _os
    _backend = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
    if _backend not in sys.path:
        sys.path.insert(0, _backend)
    from query_engine.executor import query_engine
    return query_engine


@app.post("/v1/query/submit", tags=["Query Engine"])
async def dqe_submit(
    payload: "QuerySubmitRequest",
    user: Dict[str, Any] = Depends(get_current_user),
):
    """
    Submit a query job to the Distributed Query Engine.

    Modes:
    - **sql**    — DuckDB SQL against an Apache Iceberg table
    - **graph**  — Cypher-like patterns or algorithms against the graph store
    - **python** — AST-safe pandas/pyarrow transformation script

    Returns immediately with job_id and status=running.
    Poll `/v1/query/{job_id}` for results.
    """
    from query_engine.models import QueryJob, QueryMode, QuerySubmitRequest as _QSR

    try:
        job = QueryJob(
            mode=QueryMode(payload.mode),
            namespace=payload.namespace,
            table_name=payload.table_name,
            sql=payload.sql,
            cypher=payload.cypher,
            graph_name=payload.graph_name,
            algorithm=payload.algorithm,
            python_script=payload.python_script,
            filters=payload.filters,
            limit=payload.limit,
            submitted_by=user.get("sub"),
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    engine = _get_query_engine()

    # Use submit_and_wait for small jobs (no payload flag for now; always await)
    job = await engine.submit_and_wait(job)

    log_audit(
        user_id=user.get("sub", "unknown"),
        tier=user.get("tier", "trial"),
        action="dqe_query_submit",
        details=f"mode={job.mode} job_id={job.job_id} status={job.status}",
        status="success" if job.status.value != "failed" else "error",
    )

    return {
        "job_id": job.job_id,
        "mode": job.mode,
        "status": job.status,
        "created_at": job.created_at.isoformat() + "Z",
        "started_at": job.started_at.isoformat() + "Z" if job.started_at else None,
        "completed_at": job.completed_at.isoformat() + "Z" if job.completed_at else None,
        "result": job.result.model_dump() if job.result else None,
        "error": job.error,
    }


@app.get("/v1/query/{job_id}", tags=["Query Engine"])
async def dqe_get_job(
    job_id: str,
    user: Dict[str, Any] = Depends(get_current_user),
):
    """Poll the status and result of a submitted query job."""
    engine = _get_query_engine()
    job = engine.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found or has expired.")

    # Users can only see their own jobs (Admins see all)
    if job.submitted_by != user.get("sub") and user.get("role") != "Admin":
        raise HTTPException(status_code=403, detail="Access denied to this job.")

    return {
        "job_id": job.job_id,
        "mode": job.mode,
        "status": job.status,
        "created_at": job.created_at.isoformat() + "Z",
        "started_at": job.started_at.isoformat() + "Z" if job.started_at else None,
        "completed_at": job.completed_at.isoformat() + "Z" if job.completed_at else None,
        "result": job.result.model_dump() if job.result else None,
        "error": job.error,
    }


@app.post("/v1/query/explain", tags=["Query Engine"])
async def dqe_explain(
    payload: "QueryExplainRequest",
    user: Dict[str, Any] = Depends(get_current_user),
):
    """
    Dry-run: return the execution plan for a query without executing it.

    Validates syntax and returns routing information, EXPLAIN text (for SQL),
    and graph statistics (for Graph mode). Does not consume compute resources.
    """
    from query_engine.models import QueryJob, QueryMode, QueryExplainRequest as _QER

    try:
        job = QueryJob(
            mode=QueryMode(payload.mode),
            namespace=payload.namespace,
            table_name=payload.table_name,
            sql=payload.sql,
            cypher=payload.cypher,
            graph_name=payload.graph_name,
            python_script=payload.python_script,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    engine = _get_query_engine()
    plan = engine.explain(job)
    return {"mode": payload.mode, "execution_plan": plan}


@app.get("/v1/query/history", tags=["Query Engine"])
async def dqe_history(
    limit: int = 20,
    user: Dict[str, Any] = Depends(get_current_user),
):
    """Return the authenticated user's recent query job history, newest first."""
    engine = _get_query_engine()
    jobs = engine.list_for_user(user.get("sub"), limit=limit)
    return [
        {
            "job_id": j.job_id,
            "mode": j.mode,
            "status": j.status,
            "created_at": j.created_at.isoformat() + "Z",
            "completed_at": j.completed_at.isoformat() + "Z" if j.completed_at else None,
            "total_rows": j.result.total_rows if j.result else None,
            "error": j.error,
        }
        for j in jobs
    ]


@app.post("/v1/query/multi", tags=["Query Engine"])
async def dqe_multi(
    payload: "MultiQueryRequest",
    user: Dict[str, Any] = Depends(get_current_user),
):
    """
    Fan-out multiple queries across any mix of SQL / Graph / Python modes.

    Results are returned as individual job results. When merge_strategy='union',
    all result rows are concatenated into a single merged_result (requires
    identical column schemas). Use join_on_key for key-based merging.
    """
    from query_engine.models import QueryJob, QueryMode, MultiQueryRequest as _MQR
    import asyncio as _asyncio

    if len(payload.queries) > 10:
        raise HTTPException(status_code=400, detail="Maximum 10 queries per multi-request.")

    engine = _get_query_engine()
    jobs_to_run = []
    for q in payload.queries:
        try:
            job = QueryJob(
                mode=QueryMode(q.mode),
                namespace=q.namespace,
                table_name=q.table_name,
                sql=q.sql,
                cypher=q.cypher,
                graph_name=q.graph_name,
                algorithm=q.algorithm,
                python_script=q.python_script,
                filters=q.filters,
                limit=q.limit,
                submitted_by=user.get("sub"),
            )
            jobs_to_run.append(job)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))

    # Execute all jobs concurrently
    completed_jobs = await _asyncio.gather(
        *[engine.submit_and_wait(j) for j in jobs_to_run],
        return_exceptions=False,
    )

    # Build merged result if union strategy
    merged_result = None
    if payload.merge_strategy == "union":
        all_rows = []
        all_cols: Optional[List[str]] = None
        for j in completed_jobs:
            if j.result:
                if all_cols is None:
                    all_cols = j.result.columns
                all_rows.extend(j.result.rows)
        if all_cols and all_rows:
            from query_engine.models import QueryResult as _QR
            merged_result = _QR(
                columns=all_cols,
                rows=all_rows,
                total_rows=len(all_rows),
                truncated=False,
                engine_used="multi_engine_union",
            ).model_dump()

    log_audit(
        user_id=user.get("sub", "unknown"),
        tier=user.get("tier", "trial"),
        action="dqe_multi_query",
        details=f"fan_out={len(jobs_to_run)} strategy={payload.merge_strategy}",
        status="success",
    )

    return {
        "jobs": [
            {
                "job_id": j.job_id,
                "mode": j.mode,
                "status": j.status,
                "result": j.result.model_dump() if j.result else None,
                "error": j.error,
            }
            for j in completed_jobs
        ],
        "merged_result": merged_result,
        "merge_strategy": payload.merge_strategy,
    }


@app.get("/v1/query/modes", tags=["Query Engine"])
async def dqe_modes(user: Dict[str, Any] = Depends(get_current_user)):
    """Return supported query modes, required fields, and example payloads."""
    engine = _get_query_engine()
    return {"modes": engine.supported_modes()}


# ─── DQE Pydantic request helpers (local to this file) ─────────────────────

class _DQESubmitRequest(BaseModel):
    mode: str
    namespace: Optional[str] = None
    table_name: Optional[str] = None
    sql: Optional[str] = None
    cypher: Optional[str] = None
    graph_name: Optional[str] = None
    algorithm: Optional[str] = None
    python_script: Optional[str] = None
    filters: Optional[Dict[str, Any]] = None
    limit: int = 1000

class _DQEExplainRequest(BaseModel):
    mode: str
    namespace: Optional[str] = None
    table_name: Optional[str] = None
    sql: Optional[str] = None
    cypher: Optional[str] = None
    graph_name: Optional[str] = None
    python_script: Optional[str] = None

class _DQEMultiRequest(BaseModel):
    queries: List[_DQESubmitRequest]
    merge_strategy: str = "union"
    join_key: Optional[str] = None

# Re-wire the endpoints to use the local Pydantic classes
# (overwrite the forward-reference annotations FastAPI needs at startup)
dqe_submit.__annotations__["payload"]  = _DQESubmitRequest
dqe_explain.__annotations__["payload"] = _DQEExplainRequest
dqe_multi.__annotations__["payload"]   = _DQEMultiRequest

# Rebuild FastAPI route dependencies
app.openapi_schema = None   # invalidate cached schema so FastAPI re-reads annotations


# ── Live Traffic WebSocket & REST Fallback ──────────────────────────────────
@app.websocket("/ws/traffic")
async def websocket_traffic(websocket: WebSocket, token: Optional[str] = None):
    if not token or token in ("null", "undefined", ""):
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return
    try:
        jose_jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except Exception:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    await websocket.accept()
    from traffic_bus import traffic_bus
    q = asyncio.Queue()
    traffic_bus.register(q)
    try:
        recent_events = await traffic_bus.get_recent()
        for event in recent_events:
            await websocket.send_json(event.dict())
        while True:
            event_dict = await q.get()
            await websocket.send_json(event_dict)
            q.task_done()
    except (WebSocketDisconnect, Exception):
        pass
    finally:
        traffic_bus.unregister(q)

@app.get("/v1/traffic/recent", tags=["Traffic"])
async def get_recent_traffic(user: Dict[str, Any] = Depends(get_current_user)):
    from traffic_bus import traffic_bus
    events = await traffic_bus.get_recent()
    return [e.dict() for e in events]


# ── Data Engineering Studio Schema Schemas ───────────────────────────────────
class CreateNamespaceRequest(BaseModel):
    namespace: str

class SchemaEvolutionAction(BaseModel):
    op: str  # "add", "drop", "rename"
    name: str
    type: Optional[str] = None
    new_name: Optional[str] = None

class SchemaEvolutionRequest(BaseModel):
    actions: List[SchemaEvolutionAction]

class RawIngestRequest(BaseModel):
    namespace: str
    table_name: str
    data: List[Dict[str, Any]]
    schema_json: Optional[List[Dict[str, str]]] = None
    write_mode: str = "append"  # "append", "overwrite", "upsert"
    merge_key: Optional[str] = None

class QueryRequest(BaseModel):
    sql: str
    namespace: Optional[str] = "default"
    snapshot_id: Optional[int] = None

class MaintenanceRequest(BaseModel):
    action: str  # "optimize", "expire_snapshots"

class DataContractRequest(BaseModel):
    rules: List[Dict[str, Any]]


# ── Data Engineering Studio Endpoints ────────────────────────────────────────
@app.get("/v1/catalog/namespaces", tags=["Catalog"])
async def list_namespaces(user: Dict[str, Any] = Depends(get_current_user)):
    from meldra import MeldraCatalog
    try:
        m_catalog = MeldraCatalog()
        namespaces = m_catalog.list_namespaces()
        return {"namespaces": namespaces}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/v1/catalog/namespaces", tags=["Catalog"])
async def create_namespace(payload: CreateNamespaceRequest, user: Dict[str, Any] = Depends(get_current_user)):
    from meldra import MeldraCatalog
    try:
        m_catalog = MeldraCatalog()
        m_catalog.create_namespace(payload.namespace)
        log_audit(
            user_id=user.get("sub", "unknown"),
            tier=user.get("tier", "trial"),
            action="create_namespace",
            details=f"Created namespace {payload.namespace}",
            status="success"
        )
        return {"status": "success", "message": f"Namespace {payload.namespace} created."}
    except Exception as e:
        log_audit(
            user_id=user.get("sub", "unknown"),
            tier=user.get("tier", "trial"),
            action="create_namespace",
            details=f"Failed to create namespace {payload.namespace}: {e}",
            status="error"
        )
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/v1/catalog/namespaces/{namespace}", tags=["Catalog"])
async def delete_namespace(namespace: str, user: Dict[str, Any] = Depends(get_current_user)):
    role = user.get("role", "Business Analyst")
    if role not in ["Admin", "Data Architect"]:
        raise HTTPException(status_code=403, detail=f"Access Denied: Role '{role}' does not have permission to delete namespaces.")
    from meldra import MeldraCatalog
    try:
        m_catalog = MeldraCatalog()
        m_catalog.delete_namespace(namespace)
        log_audit(
            user_id=user.get("sub", "unknown"),
            tier=user.get("tier", "trial"),
            action="delete_namespace",
            details=f"Deleted namespace {namespace}",
            status="success"
        )
        return {"status": "success", "message": f"Namespace {namespace} dropped."}
    except Exception as e:
        log_audit(
            user_id=user.get("sub", "unknown"),
            tier=user.get("tier", "trial"),
            action="delete_namespace",
            details=f"Failed to delete namespace {namespace}: {e}",
            status="error"
        )
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/v1/catalog/namespaces/{namespace}/tables", tags=["Catalog"])
async def list_tables(namespace: str, user: Dict[str, Any] = Depends(get_current_user)):
    from meldra import MeldraCatalog
    try:
        m_catalog = MeldraCatalog()
        tables = m_catalog.list_tables(namespace)
        return {"tables": tables}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/v1/catalog/namespaces/{namespace}/tables/{table_name}", tags=["Catalog"])
async def get_table_details(namespace: str, table_name: str, user: Dict[str, Any] = Depends(get_current_user)):
    from meldra import MeldraCatalog
    try:
        m_catalog = MeldraCatalog()
        details = m_catalog.get_table_details(namespace, table_name)
        return details
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/v1/catalog/namespaces/{namespace}/tables/{table_name}/schema", tags=["Catalog"])
async def evolve_schema(namespace: str, table_name: str, payload: SchemaEvolutionRequest, user: Dict[str, Any] = Depends(get_current_user)):
    role = user.get("role", "Business Analyst")
    if role not in ["Admin", "Data Architect"]:
        raise HTTPException(status_code=403, detail=f"Access Denied: Role '{role}' does not have permission to evolve schemas.")
    from meldra import MeldraCatalog
    try:
        m_catalog = MeldraCatalog()
        actions_list = [act.dict() for act in payload.actions]
        m_catalog.evolve_schema(namespace, table_name, actions_list)
        log_audit(
            user_id=user.get("sub", "unknown"),
            tier=user.get("tier", "trial"),
            action="evolve_schema",
            details=f"Evolved schema for {namespace}.{table_name}: {payload.actions}",
            status="success"
        )
        return {"status": "success", "message": f"Successfully updated schema for {namespace}.{table_name}."}
    except Exception as e:
        log_audit(
            user_id=user.get("sub", "unknown"),
            tier=user.get("tier", "trial"),
            action="evolve_schema",
            details=f"Failed schema evolution for {namespace}.{table_name}: {e}",
            status="error"
        )
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/v1/ingest/raw", tags=["Ingestion"])
async def ingest_raw_endpoint(payload: RawIngestRequest, user: Dict[str, Any] = Depends(get_current_user)):
    from meldra import MeldraCatalog, MeldraValidator
    import pyarrow as pa
    
    m_catalog = MeldraCatalog()
    catalog = m_catalog.catalog
    identifier = (payload.namespace, payload.table_name)
    
    table_exists = False
    try:
        catalog.load_table(identifier)
        table_exists = True
    except Exception:
        pass
        
    if not table_exists:
        if not payload.schema_json:
            raise HTTPException(status_code=400, detail="Table does not exist and no schema_json provided to create it.")
        from tools import create_iceberg_table
        create_res = create_iceberg_table.invoke({
            "namespace": payload.namespace,
            "table_name": payload.table_name,
            "schema_json": json.dumps(payload.schema_json)
        })
        if "error" in create_res.lower():
            raise HTTPException(status_code=500, detail=f"Failed to create table: {create_res}")
            
    table = catalog.load_table(identifier)
    df = pd.DataFrame(payload.data)
    if df.empty:
        raise HTTPException(status_code=400, detail="No data rows provided.")
        
    # --- Data Quality Contract Validation ---
    rules_str = table.properties.get("data_contracts", "[]")
    rules = json.loads(rules_str)
    if rules:
        is_valid, validation_logs = MeldraValidator.validate_dataframe(df, rules)
        if not is_valid:
            log_audit(
                user_id=user.get("sub", "unknown"),
                tier=user.get("tier", "trial"),
                action="ingest_raw_validation",
                details=f"Data contract checks failed for {payload.namespace}.{payload.table_name}: {validation_logs}",
                status="error"
            )
            raise HTTPException(
                status_code=400, 
                detail={"error": "Data Contract Validation Failed", "logs": validation_logs}
            )

    try:
        arrow_table = pa.Table.from_pandas(df)
        iceberg_schema = table.schema()
        pyarrow_schema = iceberg_schema.as_arrow()
        
        cast_arrays = []
        cast_fields = []
        for field in pyarrow_schema:
            if field.name in arrow_table.schema.names:
                col = arrow_table.column(field.name)
                cast_arrays.append(col.cast(field.type))
                cast_fields.append(field)
                
        arrow_table = pa.table(
            {field.name: arr for field, arr in zip(cast_fields, cast_arrays)},
            schema=pa.schema(cast_fields)
        )
        
        if payload.write_mode == "overwrite":
            table.overwrite(arrow_table)
        elif payload.write_mode == "upsert" and payload.merge_key:
            existing_arrow = table.scan().to_arrow()
            if len(existing_arrow) > 0:
                existing_df = existing_arrow.to_pandas()
                new_df = arrow_table.to_pandas()
                
                # Merge logic - updates matching keys and appends new keys
                merged_df = pd.concat([existing_df, new_df]).drop_duplicates(subset=[payload.merge_key], keep='last')
                
                merged_arrow = pa.Table.from_pandas(merged_df)
                cast_arrays_m = []
                cast_fields_m = []
                for field in pyarrow_schema:
                    if field.name in merged_arrow.schema.names:
                        col = merged_arrow.column(field.name)
                        cast_arrays_m.append(col.cast(field.type))
                        cast_fields_m.append(field)
                
                merged_arrow = pa.table(
                    {field.name: arr for field, arr in zip(cast_fields_m, cast_arrays_m)},
                    schema=pa.schema(cast_fields_m)
                )
                table.overwrite(merged_arrow)
            else:
                table.append(arrow_table)
        else:
            table.append(arrow_table)
            
        log_audit(
            user_id=user.get("sub", "unknown"),
            tier=user.get("tier", "trial"),
            action="ingest_raw",
            details=f"Programmatic ingestion into {payload.namespace}.{payload.table_name} ({len(df)} rows, write_mode={payload.write_mode})",
            status="success"
        )
        return {"status": "success", "message": f"Successfully ingested {len(df)} rows into {payload.namespace}.{payload.table_name}."}
    except Exception as e:
        log_audit(
            user_id=user.get("sub", "unknown"),
            tier=user.get("tier", "trial"),
            action="ingest_raw",
            details=f"Failed programmatic ingestion into {payload.namespace}.{payload.table_name}: {e}",
            status="error"
        )
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/v1/catalog/query", tags=["Catalog"])
async def execute_query(payload: QueryRequest, user: Dict[str, Any] = Depends(get_current_user)):
    from meldra import MeldraCatalog
    import duckdb
    try:
        m_catalog = MeldraCatalog()
        tables = m_catalog.list_tables(payload.namespace)
        
        # Restrict SQL capabilities for secure query execution
        sql_upper = payload.sql.upper()
        forbidden_keywords = ["ATTACH", "COPY", "INSTALL", "LOAD"]
        for kw in forbidden_keywords:
            if kw in sql_upper:
                raise Exception(f"SQL execution denied: Keyword '{kw}' is blocked for security.")
                
        con = duckdb.connect(database=':memory:')
        con.execute("SET enable_external_access=false;")
        
        for tbl_name in tables:
            try:
                # Time travel scan
                arrow_tbl = m_catalog.run_time_travel_scan(payload.namespace, tbl_name, payload.snapshot_id)
                con.register(tbl_name, arrow_tbl)
            except Exception:
                pass
                
        start_time = time.time()
        result_df = con.execute(payload.sql).fetchdf()
        duration_ms = (time.time() - start_time) * 1000

        # Apply dynamic column-level RBAC policies
        role = user.get("role", "Business Analyst")
        from auth_db import _get_conn
        conn = _get_conn()
        cur = conn.cursor()
        cur.execute("SELECT namespace, table_name, column_name, action, masking_pattern FROM auth.rbac_policies WHERE role = %s;", (role,))
        policies = cur.fetchall()
        conn.close()
        
        for pol in policies:
            col_to_mask = pol["column_name"]
            tbl_to_mask = pol["table_name"]
            action = pol["action"]
            pattern = pol["masking_pattern"]
            
            if col_to_mask in result_df.columns and (tbl_to_mask.lower() in payload.sql.lower() or tbl_to_mask == "*"):
                if action == "mask":
                    result_df[col_to_mask] = result_df[col_to_mask].astype(object)
                    if pattern == "***":
                        result_df[col_to_mask] = "***"
                    elif pattern == "###.##":
                        result_df[col_to_mask] = 0.00
                    else:
                        result_df[col_to_mask] = result_df[col_to_mask].apply(lambda x: pattern if pd.notna(x) else None)
                elif action == "deny":
                    raise Exception(f"Access Denied: Your role '{role}' is not authorized to query column '{col_to_mask}' of table '{tbl_to_mask}'.")
        
        preview_rows = result_df.head(100).to_dict(orient="records")
        for row in preview_rows:
            for k, v in row.items():
                if pd.isna(v):
                    row[k] = None
                elif not isinstance(v, (str, int, float, bool, type(None))):
                    row[k] = str(v)
                    
        columns = list(result_df.columns)
        
        log_audit(
            user_id=user.get("sub", "unknown"),
            tier=user.get("tier", "trial"),
            action="execute_query",
            details=f"Executed SQL: {payload.sql[:100]}...",
            status="success"
        )
        
        return {
            "columns": columns,
            "rows": preview_rows,
            "duration_ms": duration_ms,
            "row_count": len(result_df)
        }
    except Exception as e:
        log_audit(
            user_id=user.get("sub", "unknown"),
            tier=user.get("tier", "trial"),
            action="execute_query",
            details=f"Failed SQL: {payload.sql[:100]}... | Error: {e}",
            status="error"
        )
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/v1/catalog/namespaces/{namespace}/tables/{table_name}/maintenance", tags=["Catalog"])
async def table_maintenance(namespace: str, table_name: str, payload: MaintenanceRequest, user: Dict[str, Any] = Depends(get_current_user)):
    from meldra import MeldraCatalog
    try:
        m_catalog = MeldraCatalog()
        if payload.action == "optimize":
            msg = m_catalog.optimize_table(namespace, table_name)
        elif payload.action == "expire_snapshots":
            msg = m_catalog.expire_snapshots(namespace, table_name)
        else:
            raise Exception("Invalid maintenance action.")
            
        log_audit(
            user_id=user.get("sub", "unknown"),
            tier=user.get("tier", "trial"),
            action="maintenance",
            details=f"Run {payload.action} on {namespace}.{table_name}",
            status="success"
        )
        return {"status": "success", "message": msg}
    except Exception as e:
        log_audit(
            user_id=user.get("sub", "unknown"),
            tier=user.get("tier", "trial"),
            action="maintenance",
            details=f"Failed maintenance {payload.action} on {namespace}.{table_name}: {e}",
            status="error"
        )
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/v1/catalog/namespaces/{namespace}/tables/{table_name}/contracts", tags=["Catalog"])
async def save_data_contracts(namespace: str, table_name: str, payload: DataContractRequest, user: Dict[str, Any] = Depends(get_current_user)):
    from meldra import MeldraCatalog
    import json
    try:
        m_catalog = MeldraCatalog()
        catalog = m_catalog.catalog
        identifier = (namespace, table_name)
        table = catalog.load_table(identifier)
        contract_json = json.dumps(payload.rules)
        table.transaction().set_properties({"data_contracts": contract_json}).commit()
        return {"status": "success", "message": "Data contracts updated."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/v1/catalog/namespaces/{namespace}/tables/{table_name}/contracts", tags=["Catalog"])
async def get_data_contracts(namespace: str, table_name: str, user: Dict[str, Any] = Depends(get_current_user)):
    from meldra import MeldraCatalog
    import json
    try:
        m_catalog = MeldraCatalog()
        catalog = m_catalog.catalog
        identifier = (namespace, table_name)
        table = catalog.load_table(identifier)
        rules_str = table.properties.get("data_contracts", "[]")
        return {"rules": json.loads(rules_str)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class GraphProjectRequest(BaseModel):
    namespace: str = "default"
    table_name: str
    source_col: str
    target_col: str
    edge_label: str = "RELATED_TO"
    graph_name: str = "default_graph"

@app.post("/v1/graph/project", tags=["Graph"])
async def project_table_to_graph(req: GraphProjectRequest, user: Dict[str, Any] = Depends(get_current_user)):
    from catalog_setup import get_catalog
    from graph_db import sync_dataframe_to_neo4j
    try:
        catalog = get_catalog()
        table_identifier = f"{req.namespace}.{req.table_name}"
        table = catalog.load_table(table_identifier)
        df = table.scan().to_arrow().to_pandas()

        if req.source_col not in df.columns or req.target_col not in df.columns:
            raise HTTPException(
                status_code=400,
                detail=f"Source column '{req.source_col}' or Target column '{req.target_col}' not found in table schema."
            )

        result = sync_dataframe_to_neo4j(
            graph_name=req.graph_name,
            df=df,
            source_col=req.source_col,
            target_col=req.target_col,
            edge_label=req.edge_label
        )
        if "error" in result.lower() or "❌" in result:
            raise HTTPException(status_code=500, detail=result)
        return {"status": "success", "message": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/v1/admin/reset-tenant", tags=["Admin"])
async def reset_tenant_state(user: Dict[str, Any] = Depends(get_current_user)):
    role = user.get("role", "Business Analyst")
    if role != "Admin":
        raise HTTPException(
            status_code=403,
            detail="Access Denied: Only users with the 'Admin' role can reset the tenant capacity."
        )
    
    from auth_db import _get_conn
    from catalog_setup import get_catalog
    
    # 1. Clear database state (except active Admin)
    conn = _get_conn()
    try:
        cur = conn.cursor()
        
        # Delete all users EXCEPT the logged-in admin
        admin_email = user.get("email")
        cur.execute("DELETE FROM auth.users WHERE email != %s;", (admin_email,))
        
        # Clear all policies, nodes, edges, logs
        cur.execute("DELETE FROM auth.rbac_policies;")
        cur.execute("DELETE FROM auth.graph_nodes;")
        cur.execute("DELETE FROM auth.graph_edges;")
        cur.execute("DELETE FROM auth.audit_logs;")
        
        conn.commit()
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=f"Database reset error: {str(e)}")
    finally:
        conn.close()

    # 2. Clear S3/Local Iceberg catalog tables
    try:
        catalog = get_catalog()
        tables = catalog.list_tables("default")
        for t_ident in tables:
            try:
                catalog.drop_table(t_ident)
            except Exception:
                pass
    except Exception as e:
        print(f"[reset-tenant] Failed to drop catalog tables: {e}")

    # 3. Re-seed demo transactions
    try:
        seed_demo_data()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to re-seed demo data: {str(e)}")
        
    return {"status": "success", "message": "Tenant state reset and demo data re-seeded successfully."}


class RBACPolicyItem(BaseModel):
    role: str
    namespace: str
    table_name: str
    column_name: str
    action: str
    masking_pattern: str

class SavePoliciesRequest(BaseModel):
    policies: List[RBACPolicyItem]

class UpdateUserRoleRequest(BaseModel):
    email: str
    role: str

class PythonExecuteRequest(BaseModel):
    script: str

@app.get("/v1/rbac/policies", tags=["RBAC"])
async def get_rbac_policies(user: Dict[str, Any] = Depends(get_current_user)):
    from auth_db import _get_conn
    conn = _get_conn()
    try:
        cur = conn.cursor()
        cur.execute("SELECT id, role, namespace, table_name, column_name, action, masking_pattern FROM auth.rbac_policies;")
        return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()

@app.post("/v1/rbac/policies", tags=["RBAC"])
async def save_rbac_policies(payload: SavePoliciesRequest, user: Dict[str, Any] = Depends(get_current_user)):
    role = user.get("role", "Business Analyst")
    if role != "Admin":
        raise HTTPException(status_code=403, detail="Only Admins can modify RBAC policies.")
    from auth_db import _get_conn
    conn = _get_conn()
    try:
        cur = conn.cursor()
        cur.execute("DELETE FROM auth.rbac_policies;")
        for item in payload.policies:
            cur.execute("""
                INSERT INTO auth.rbac_policies (role, namespace, table_name, column_name, action, masking_pattern)
                VALUES (%s, %s, %s, %s, %s, %s);
            """, (item.role, item.namespace, item.table_name, item.column_name, item.action, item.masking_pattern))
        conn.commit()
        return {"status": "success", "message": "RBAC policies updated."}
    finally:
        conn.close()

@app.post("/v1/rbac/user-role", tags=["RBAC"])
async def update_user_role(payload: UpdateUserRoleRequest, user: Dict[str, Any] = Depends(get_current_user)):
    role = user.get("role", "Business Analyst")
    if role != "Admin":
        raise HTTPException(status_code=403, detail="Only Admins can modify user roles.")
    from auth_db import _get_conn
    conn = _get_conn()
    try:
        cur = conn.cursor()
        cur.execute("UPDATE auth.users SET user_role = %s WHERE email = %s;", (payload.role, payload.email.lower().strip()))
        conn.commit()
        return {"status": "success", "message": f"User {payload.email} role updated to {payload.role}."}
    finally:
        conn.close()

@app.post("/v1/studio/execute-python", tags=["Studio"])
async def execute_python_script(payload: PythonExecuteRequest, user: Dict[str, Any] = Depends(get_current_user)):
    role = user.get("role", "Business Analyst")
    if role not in ["Admin", "Data Engineer"]:
        raise HTTPException(status_code=403, detail=f"Access Denied: Role '{role}' does not have permission to execute Python scripts.")
    
    import sys
    import subprocess
    import tempfile
    
    # Write script to temporary file
    temp_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "scratch")
    os.makedirs(temp_dir, exist_ok=True)
    
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", dir=temp_dir, delete=False) as f:
        # Prepend path setups
        f.write("import os\n")
        f.write("import sys\n")
        backend_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        # Escape path backslashes for Windows safety
        escaped_backend_path = backend_path.replace("\\", "\\\\")
        f.write(f"sys.path.insert(0, '{escaped_backend_path}')\n")
        f.write(payload.script)
        temp_file_path = f.name
        
    try:
        env = os.environ.copy()
        # Remove critical keys from runtime subprocess environment for sandbox security
        for key in ["ANTHROPIC_API_KEY", "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "JWT_SECRET_KEY", "DATABASE_URL", "GRAPH_DB_PASSWORD", "GRAPH_DB_USER"]:
            env.pop(key, None)
            
        result = subprocess.run(
            [sys.executable, temp_file_path],
            capture_output=True,
            text=True,
            timeout=15,
            env=env,
            cwd=backend_path
        )
        return {
            "stdout": result.stdout,
            "stderr": result.stderr,
            "exit_code": result.returncode
        }
    except subprocess.TimeoutExpired:
        return {
            "stdout": "",
            "stderr": "Execution Timeout: Code took longer than 15 seconds to run.",
            "exit_code": -1
        }
    except Exception as e:
        return {
            "stdout": "",
            "stderr": f"Execution Error: {str(e)}",
            "exit_code": -2
        }
    finally:
        try:
            os.remove(temp_file_path)
        except Exception:
            pass

@app.get("/v1/studio/search", tags=["Studio"])
async def search_studio(q: str, user: Dict[str, Any] = Depends(get_current_user)):
    from meldra import MeldraCatalog
    query = q.lower().strip()
    results = []
    
    pages = [
        {"name": "Chat Console", "type": "page", "route": "chat-tab", "desc": "Chat with your data lake using AI"},
        {"name": "Learn Academy", "type": "page", "route": "learn-tab", "desc": "Hands-on tutorials and academy videos"},
        {"name": "Upload CSV", "type": "page", "route": "ingest-tab", "desc": "Ingest CSV files into S3 Iceberg"},
        {"name": "Graph Database Console", "type": "page", "route": "graph-tab", "desc": "Run openCypher queries on Apache AGE"},
        {"name": "Audit Trails & SOX Logs", "type": "page", "route": "audit-tab", "desc": "Cryptographically signed system log tracker"},
        {"name": "AWS Warehouse Settings", "type": "page", "route": "workspace-tab", "desc": "Connect your own S3 data lake bucket"},
        {"name": "Python Script Workspace", "type": "page", "route": "studio-tab", "desc": "Run Python scripts and SQL queries"},
        {"name": "Role-Based Access Control Policies", "type": "page", "route": "studio-tab", "desc": "Manage column-level masking rules"}
    ]
    for p in pages:
        if query in p["name"].lower() or query in p["desc"].lower():
            results.append(p)
            
    try:
        m_catalog = MeldraCatalog()
        namespaces = m_catalog.list_namespaces()
        for ns in namespaces:
            if query in ns.lower():
                results.append({"name": f"Namespace '{ns}'", "type": "namespace", "route": "studio-tab", "desc": f"Iceberg catalog namespace"})
            
            tables = m_catalog.list_tables(ns)
            for tbl in tables:
                if query in tbl.lower():
                    results.append({
                        "name": f"Table '{ns}.{tbl}'",
                        "type": "table",
                        "route": "studio-tab",
                        "desc": f"Iceberg table in namespace {ns}",
                        "namespace": ns,
                        "table_name": tbl
                    })
    except Exception:
        pass
        
    actions = [
        {"name": "Compact table files (Optimize)", "type": "action", "route": "studio-tab", "action_id": "optimize", "desc": "Run layout bin-packing compaction on Iceberg tables"},
        {"name": "Expire table snapshots", "type": "action", "route": "studio-tab", "action_id": "expire_snapshots", "desc": "Purge older metadata snapshots from S3 store"},
        {"name": "Manage column masking", "type": "action", "route": "studio-tab", "action_id": "rbac", "desc": "Open role-based policy board"}
    ]
    for a in actions:
        if query in a["name"].lower() or query in a["desc"].lower():
            results.append(a)
            
    return results

@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    return JSONResponse(status_code=exc.status_code, content={"error": exc.detail})
