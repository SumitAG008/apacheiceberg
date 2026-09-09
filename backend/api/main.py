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
from fastapi.responses import JSONResponse, RedirectResponse, Response
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
    get_or_create_sso_user,
    set_user_approver,
    list_approvers,
    list_all_users,
    ensure_bootstrap_admin,
    create_promotion,
    list_promotions,
    get_promotion,
    decide_promotion,
)
import oidc
import saml
from mfa_service import send_email_otp
from roles import (
    ALL_ROLES,
    ROLE_DESCRIPTIONS,
    ROLE_ADMIN,
    ROLE_BUSINESS_ANALYST,
    CAN_RUN_PYTHON,
    CAN_MANAGE_SCHEMA,
    CAN_MANAGE_RBAC,
    CAN_INGEST,
    DASHBOARD_ONLY_ROLES,
)

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
JWT_API_TOKEN_EXPIRE_DAYS = int(os.environ.get("JWT_API_TOKEN_EXPIRE_DAYS", 90))

def _safe_iso(val: Any) -> Optional[str]:
    """Safely convert a datetime object or string to an ISO formatted string without crashing."""
    if val is None:
        return None
    if hasattr(val, "isoformat"):
        return val.isoformat()
    return str(val)

app = FastAPI(
    title="Meldra AI — LakeMind Iceberg API",
    version="1.0.0",
    docs_url="/docs",
    description="Proprietary API. Copyright 2025 Meldra AI Ltd. All rights reserved.",
)

# Allow calling from frontend origin
cors_origins_raw = os.environ.get("CORS_ALLOW_ORIGINS")
if cors_origins_raw:
    # Split and strip whitespaces to prevent parsing errors
    cors_origins = [origin.strip() for origin in cors_origins_raw.split(",") if origin.strip()]
else:
    cors_origins = [
        "http://localhost:5173", 
        "http://localhost:3000", 
        "http://127.0.0.1:5173",
        "https://zerocopy.meldra.ai"
    ]

# Foolproof fallback: always append default UI origins to ensure no CORS blocking
always_allowed = ["https://zerocopy.meldra.ai", "http://localhost:5173", "http://127.0.0.1:5173"]
for origin in always_allowed:
    if origin not in cors_origins:
        cors_origins.append(origin)

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
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
        import os
        from arrow_flight_server import meldraFlightServer
        def run_flight():
            try:
                flight_port = int(os.getenv("ARROW_FLIGHT_PORT", 8889))
                server = meldraFlightServer(host="0.0.0.0", port=flight_port)
                print(f"[api/main] Starting Arrow Flight Server on port {flight_port}...")
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

class SmartMeterHesRequest(BaseModel):
    hes_endpoint: str         # e.g. https://hes-gateway.utility.internal
    company_id: str           # e.g. DNO_TENANT_01
    auth_type: str            # "basic" or "oauth2"
    username: Optional[str] = None
    password: Optional[str] = None
    client_id: Optional[str] = None
    client_secret: Optional[str] = None
    token_url: Optional[str] = None
    entity_name: str          # e.g. IntervalReadings, UsagePoints, MeterEvents
    top: Optional[int] = 1000
    select_fields: Optional[List[str]] = None
    namespace: str = "default"
    table_name: str
    write_mode: Optional[str] = "overwrite"


class SmartMeterHesTestRequest(BaseModel):
    hes_endpoint: str
    company_id: str
    auth_type: str
    username: Optional[str] = None
    password: Optional[str] = None
    client_id: Optional[str] = None
    client_secret: Optional[str] = None
    token_url: Optional[str] = None

class CypherRequest(BaseModel):
    graph_name: str
    query: str

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


def _create_api_token(data: Dict[str, Any]) -> str:
    """Long-lived token for external/programmatic clients (e.g. the MCP
    server) that can't complete the interactive OTP login flow. Minted
    on-demand by an already-authenticated user via POST /auth/api-token."""
    payload = data.copy()
    payload["exp"] = datetime.utcnow() + timedelta(days=JWT_API_TOKEN_EXPIRE_DAYS)
    payload["iat"] = datetime.utcnow()
    payload["type"] = "api"
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
    return _decode_temp_token_with_purpose(token)[0]


def _decode_temp_token_with_purpose(token: str) -> tuple[str, str]:
    """Decode temp token, return (user_id, otp_purpose) or raise 401.

    The OTP purpose ('register' | 'login' | 'reset') is read from the token
    itself rather than re-derived from the user's current `is_verified`
    state — that state can change between issuing the OTP and verifying it
    (e.g. a user who abandons registration and later just tries to log in),
    which previously caused verify-mfa to check the wrong OTP bucket and
    always report "expired"/"no active OTP" regardless of the real code.
    """
    try:
        payload = jose_jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        if payload.get("type") != "temp":
            print(f"[auth] _decode_temp_token: Invalid token type in payload: {payload}")
            raise HTTPException(status_code=401, detail="Invalid token type")
        return payload["sub"], payload.get("purpose", "login")
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
        if payload.get("type") not in ("access", "api"):
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

    check_register_rate_limit(reg_ip)

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

    temp_token = _create_temp_token(str(user["id"]), purpose="register")
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

# Rate limiting cache for registration attempts, keyed by IP (unlike login,
# every registration attempt uses a different email, so email-keying would
# do nothing to stop mass account creation / OTP-email spam from one source).
registration_attempts = defaultdict(list)

def check_register_rate_limit(ip: str):
    now = time.time()
    attempts = [t for t in registration_attempts[ip] if now - t < 3600]
    attempts.append(now)
    registration_attempts[ip] = attempts
    if len(attempts) > 5:
        raise HTTPException(
            status_code=429,
            detail="Too many registration attempts from this address. Please try again later."
        )


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

    temp_token = _create_temp_token(str(user["id"]), purpose="login")
    log_audit(str(user["id"]), user["tier"], "login_attempt", f"OTP sent to {payload.email}", "success")

    return {
        "message": f"Verification code sent to {payload.email}.",
        "temp_token": temp_token,
        "mfa_required": True,
    }


@app.post("/auth/verify-mfa", response_model=TokenResponse, tags=["Auth"])
async def verify_mfa(payload: VerifyMFARequest):
    """Step 2: validate OTP, return access + refresh tokens."""
    user_id, purpose = _decode_temp_token_with_purpose(payload.temp_token)
    user = get_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=401, detail="User not found.")

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

    # Platform-wide bootstrap: if nobody is Admin yet, this user becomes the
    # first one (see ensure_bootstrap_admin's docstring for why this exists).
    bootstrapped_role = ensure_bootstrap_admin(user_id)
    effective_role = bootstrapped_role or user.get("user_role", "Business Analyst")

    # Issue tokens using user's database tier and role
    access_token = _create_access_token({
        "sub": user_id,
        "email": user["email"],
        "tier": user["tier"],
        "role": effective_role
    })
    refresh_token = create_session(user_id)

    log_audit(user_id, user["tier"], "mfa_verify", f"MFA verified for {user['email']}", "success")

    expires_str = _safe_iso(user.get("expires_at"))

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
            "role": effective_role,
            "reg_ip": user.get("reg_ip"),
            "reg_country": user.get("reg_country"),
            "subscription_status": user["subscription_status"],
        },
    )


@app.post("/auth/resend-otp", tags=["Auth"])
async def resend_otp(payload: ResendOTPRequest):
    """Resend OTP — rate-limited to once per 60 seconds."""
    user_id, purpose = _decode_temp_token_with_purpose(payload.temp_token)
    user = get_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=401, detail="User not found.")

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

    temp_token = _create_temp_token(str(user["id"]), purpose="reset")
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
        "created_at": _safe_iso(db_user.get("created_at")),
        "last_login_at": _safe_iso(db_user.get("last_login_at")),
        "role": db_user.get("user_role", "Business Analyst"),
        "is_approver": bool(db_user.get("is_approver", False)),
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


@app.get("/auth/sso/status", tags=["Auth"])
async def sso_status():
    """Public — lets the frontend know whether to show a 'Sign in with X'
    button at all, and what to label it. No secrets in the response."""
    configured = oidc.is_configured()
    return {"configured": configured, "provider_name": oidc.provider_name() if configured else None}


@app.get("/auth/sso/login", tags=["Auth"])
async def sso_login():
    """Redirects the browser to the configured identity provider's login page."""
    if not oidc.is_configured():
        raise HTTPException(status_code=501, detail="SSO is not configured on this deployment.")
    try:
        url = oidc.build_authorization_url()
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Could not reach the identity provider: {e}")
    return RedirectResponse(url)


@app.get("/auth/sso/callback", tags=["Auth"])
async def sso_callback(code: str = "", state: str = "", error: str = ""):
    """
    The IdP redirects the browser here after login. Exchanges the
    authorization code for a verified id_token (see oidc.exchange_code_for_claims),
    looks up or provisions the local user by the email claim, and redirects
    to the frontend carrying our own access + refresh tokens — the SSO user
    ends up in exactly the same session state a password+MFA login produces.
    """
    frontend_url = os.environ.get("FRONTEND_URL", "http://localhost:5173")

    if error:
        return RedirectResponse(f"{frontend_url}/?sso_error={error}")

    if not oidc.is_configured():
        raise HTTPException(status_code=501, detail="SSO is not configured on this deployment.")

    if not state or not oidc.consume_state(state):
        return RedirectResponse(f"{frontend_url}/?sso_error=invalid_state")

    try:
        claims = oidc.exchange_code_for_claims(code)
    except Exception as e:
        log_audit_pg("unknown", "trial", "sso_login", f"Code exchange/verification failed: {e}", "error")
        return RedirectResponse(f"{frontend_url}/?sso_error=exchange_failed")

    email = claims.get("email")
    if not email:
        return RedirectResponse(f"{frontend_url}/?sso_error=no_email_claim")

    user = get_or_create_sso_user(email, provider=oidc.provider_name())
    update_last_login(user["id"])

    access_token = _create_access_token({
        "sub": user["id"],
        "email": user["email"],
        "tier": user["tier"],
        "role": user.get("user_role", "Business Analyst"),
    })
    refresh_token = create_session(user["id"])

    log_audit_pg(user["id"], user["tier"], "sso_login", f"SSO login via {oidc.provider_name()} for {email}", "success")

    import json as _json
    import base64 as _base64
    user_payload = _base64.urlsafe_b64encode(_json.dumps({
        "id": user["id"],
        "email": user["email"],
        "mfa_method": user.get("mfa_method", "email"),
        "is_verified": True,
        "tier": user["tier"],
        "role": user.get("user_role", "Business Analyst"),
        "subscription_status": user.get("subscription_status", "active"),
    }).encode()).decode()

    return RedirectResponse(
        f"{frontend_url}/?sso_access_token={access_token}&sso_refresh_token={refresh_token}&sso_user={user_payload}"
    )


@app.get("/auth/saml/status", tags=["Auth"])
async def saml_status():
    """Public — returns whether Enterprise SAML 2.0 SSO is configured."""
    configured = saml.is_configured()
    return {"configured": configured, "provider_name": saml.provider_name() if configured else None}


@app.get("/auth/saml/login", tags=["Auth"])
async def saml_login(relay_state: Optional[str] = None):
    """Initiates SAML 2.0 SP-initiated SSO, redirecting to the enterprise IdP."""
    if not saml.is_configured():
        raise HTTPException(status_code=501, detail="SAML 2.0 SSO is not configured on this deployment.")
    try:
        redirect_url = saml.build_authn_request_url(relay_state=relay_state)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Could not build SAML AuthnRequest: {e}")
    return RedirectResponse(redirect_url)


@app.post("/auth/saml/acs", tags=["Auth"])
async def saml_acs(request: Request):
    """
    Assertion Consumer Service (ACS).
    Receives HTTP-POST binding SAMLResponse from IdP, validates XML assertion,
    provisions or loads the SSO user, and redirects to frontend with auth tokens.
    """
    frontend_url = os.environ.get("FRONTEND_URL", "http://localhost:5173")
    if not saml.is_configured():
        raise HTTPException(status_code=501, detail="SAML 2.0 SSO is not configured on this deployment.")

    form_data = await request.form()
    saml_response_b64 = form_data.get("SAMLResponse")
    relay_state = form_data.get("RelayState", "")

    if not saml_response_b64:
        return RedirectResponse(f"{frontend_url}/?saml_error=missing_saml_response")

    if relay_state and not saml.validate_relay_state(str(relay_state)):
        logger.warning("[SAML] Invalid or expired relay state: %s", relay_state)
        return RedirectResponse(f"{frontend_url}/?saml_error=invalid_relay_state")

    try:
        claims = saml.parse_saml_response(str(saml_response_b64))
    except Exception as e:
        log_audit_pg("unknown", "trial", "saml_login", f"SAML assertion processing failed: {e}", "error")
        return RedirectResponse(f"{frontend_url}/?saml_error=assertion_invalid")

    email = claims.get("email")
    if not email:
        return RedirectResponse(f"{frontend_url}/?saml_error=no_email_claim")

    # Map enterprise role or fallback to Business Analyst
    assigned_role = "Business Analyst"
    saml_roles = claims.get("roles", [])
    if any("admin" in str(r).lower() for r in saml_roles):
        assigned_role = "Admin"
    elif any("engineer" in str(r).lower() for r in saml_roles):
        assigned_role = "Data Engineer"

    user = get_or_create_sso_user(email, provider=saml.provider_name(), user_role=assigned_role)
    update_last_login(user["id"])

    access_token = _create_access_token({
        "sub": user["id"],
        "email": user["email"],
        "tier": user["tier"],
        "role": user.get("user_role", assigned_role),
    })
    refresh_token = create_session(user["id"])

    log_audit_pg(user["id"], user["tier"], "saml_login", f"SSO login via SAML for {email}", "success")

    import json as _json
    import base64 as _base64
    user_payload = _base64.urlsafe_b64encode(_json.dumps({
        "id": user["id"],
        "email": user["email"],
        "mfa_method": user.get("mfa_method", "email"),
        "is_verified": True,
        "tier": user["tier"],
        "role": user.get("user_role", assigned_role),
        "subscription_status": user.get("subscription_status", "active"),
    }).encode()).decode()

    return RedirectResponse(
        f"{frontend_url}/?sso_access_token={access_token}&sso_refresh_token={refresh_token}&sso_user={user_payload}"
    )


@app.get("/auth/saml/metadata", tags=["Auth"])
async def saml_metadata():
    """Returns Service Provider (SP) SAML 2.0 metadata XML for IdP setup."""
    xml_content = saml.generate_sp_metadata()
    return Response(content=xml_content, media_type="application/xml")


@app.post("/auth/api-token", tags=["Auth"])
async def generate_api_token(user: Dict[str, Any] = Depends(get_current_user)):
    """
    Mint a long-lived API token for external/programmatic access — the same
    RBAC- and tenant-scoped credential the real MCP server (backend/mcp_server.py)
    and any other API client use. Requires an active session; shown once.
    """
    token = _create_api_token({
        "sub": user["sub"],
        "email": user.get("email"),
        "tier": user.get("tier"),
        "role": user.get("role", "Business Analyst"),
    })
    expires_at = datetime.utcnow() + timedelta(days=JWT_API_TOKEN_EXPIRE_DAYS)
    log_audit(
        user_id=user.get("sub", "unknown"),
        tier=user.get("tier", "trial"),
        action="generate_api_token",
        details=f"Minted API token expiring {expires_at.isoformat()}Z",
        status="success",
    )
    return {
        "api_token": token,
        "expires_at": expires_at.isoformat() + "Z",
        "token_type": "bearer",
    }


# ─────────────────────────────────────────
# META ENDPOINTS
# ─────────────────────────────────────────
@app.get("/health", tags=["Meta"])
async def health_check():
    return {"status": "ok"}


@app.get("/v1/audit", tags=["Audit"])
async def get_audit_trail(user: Dict[str, Any] = Depends(get_current_user)):
    # Every account is its own tenant, so "your audit trail" means your own
    # actions -- not the whole platform's. Admins can see everything (the
    # only cross-tenant view anywhere in the app, and an intentional one).
    scoped_user_id = None if user.get("role") == "Admin" else user.get("sub")
    try:
        logs = get_audit_logs_pg(limit=100, user_id=scoped_user_id)
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

    # Thread this request's tenant + role into the Agent's tools via
    # ContextVar (their signatures are fixed by the LLM tool-calling schema,
    # so this can't be passed as a normal argument) — the Agent is then
    # structurally scoped to this tenant's own data and this role's RBAC
    # policies for every tool call it makes, not just trusted to behave.
    from tenancy import get_current_tenant_id
    from tools import current_tenant_id, current_user_role
    tenant_token = current_tenant_id.set(get_current_tenant_id(user))
    role_token = current_user_role.set(user.get("role", "Business Analyst"))

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
    finally:
        current_tenant_id.reset(tenant_token)
        current_user_role.reset(role_token)

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
    if user.get("role", "Business Analyst") not in CAN_INGEST:
        raise HTTPException(
            status_code=403,
            detail=f"Access Denied: Role '{user.get('role')}' does not have permission to ingest data."
        )
    from catalog_setup import get_catalog
    from tools import create_iceberg_table
    from tenancy import get_current_tenant_id, scope_namespace
    import pyarrow as pa
    import pyarrow.csv as pv

    # Scope the namespace to this tenant once, up front — every reference
    # to payload.namespace below (table creation, catalog load, audit log)
    # then automatically operates on the tenant-isolated namespace without
    # needing individual changes throughout this function.
    payload.namespace = scope_namespace(get_current_tenant_id(user), payload.namespace)

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
    if user.get("role") != "Admin":
        raise HTTPException(status_code=403, detail="Only Admins can view AWS config")
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
    if user.get("role") != "Admin":
        raise HTTPException(status_code=403, detail="Only Admins can modify AWS config")
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


@app.post("/v1/connectors/hes/test", tags=["Ingestion"])
async def test_hes_connection(
    payload: SmartMeterHesTestRequest,
    user: Dict[str, Any] = Depends(get_current_user)
):
    """
    Real connection test for the Smart Meter HES Connector wizard's "Test Connection" button.
    Fetches the tenant's own OData $metadata (EDMX/CSDL XML) and returns every EntityType it defines,
    so the "Target Object / Entity" dropdown reflects what this specific HES instance actually supports.

    Also returns each entity's real Property names (entity_fields), so the
    UI can offer a field-level checklist -- e.g. the MeterReadings entity --
    without a second round-trip, since $metadata already contains them all.
    """
    import time
    import requests
    import xml.etree.ElementTree as ET

    base_url = payload.hes_endpoint.rstrip("/")

    session = requests.Session()
    if payload.auth_type == "basic":
        if not payload.username or not payload.password:
            raise HTTPException(status_code=400, detail="username and password are required for Basic auth")
        session.auth = (f"{payload.username}@{payload.company_id}", payload.password)
    elif payload.auth_type == "oauth2":
        if not payload.client_id or not payload.client_secret:
            raise HTTPException(status_code=400, detail="client_id and client_secret are required for OAuth2")
        token_url = payload.token_url or f"{base_url}/oauth/token"
        try:
            token_resp = requests.post(token_url, data={
                "grant_type": "client_credentials",
                "client_id": payload.client_id,
                "client_secret": payload.client_secret,
                "company_id": payload.company_id,
            }, timeout=30)
            token_resp.raise_for_status()
            access_token = token_resp.json().get("access_token")
            if not access_token:
                raise HTTPException(status_code=401, detail=f"OAuth2 token response missing access_token: {token_resp.text}")
            session.headers["Authorization"] = f"Bearer {access_token}"
        except requests.RequestException as e:
            raise HTTPException(status_code=502, detail=f"OAuth2 token fetch failed: {e}")
    else:
        raise HTTPException(status_code=400, detail="auth_type must be 'basic' or 'oauth2'")

    metadata_url = f"{base_url}/odata/v2/$metadata"
    start = time.monotonic()
    try:
        resp = session.get(metadata_url, timeout=30)
        resp.raise_for_status()
    except requests.RequestException as e:
        raise HTTPException(status_code=502, detail=f"Could not reach {metadata_url}: {e}")
    latency_ms = round((time.monotonic() - start) * 1000)

    try:
        root = ET.fromstring(resp.content)
    except ET.ParseError as e:
        raise HTTPException(status_code=502, detail=f"$metadata response wasn't valid XML: {e}")

    # Namespace-agnostic: match on local tag name rather than a hardcoded namespace.
    entity_fields: Dict[str, List[str]] = {}
    for el in root.iter():
        if el.tag.rsplit("}", 1)[-1] == "EntityType" and "Name" in el.attrib:
            fields = sorted(
                child.attrib["Name"]
                for child in el
                if child.tag.rsplit("}", 1)[-1] == "Property" and "Name" in child.attrib
            )
            entity_fields[el.attrib["Name"]] = fields

    entities = sorted(entity_fields.keys())

    if not entities:
        raise HTTPException(status_code=502, detail="Connected, but $metadata listed zero EntityType definitions.")

    return {
        "connected": True,
        "latency_ms": latency_ms,
        "entity_count": len(entities),
        "entities": entities,
        "entity_fields": entity_fields,
    }


@app.post("/v1/ingest/hes", tags=["Ingestion"])
async def ingest_hes(
    payload: SmartMeterHesRequest,
    user: Dict[str, Any] = Depends(get_current_user)
):
    """
    Fetch data from Smart Meter HES OData API and ingest into the Iceberg lakehouse.
    Supports Basic Auth and OAuth2 Client Credentials flow.
    Handles OData pagination ($skiptoken / @odata.nextLink) automatically.
    """
    if user.get("role", "Business Analyst") not in CAN_INGEST:
        raise HTTPException(
            status_code=403,
            detail=f"Access Denied: Role '{user.get('role')}' does not have permission to ingest data."
        )
    from tenancy import get_current_tenant_id, scope_namespace
    payload.namespace = scope_namespace(get_current_tenant_id(user), payload.namespace)
    import requests
    import pyarrow as pa
    from catalog_setup import get_catalog
    from tools import create_iceberg_table

    base_url = payload.hes_endpoint.rstrip("/")
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
        hes_user = f"{payload.username}@{company_id}"
        session.auth = (hes_user, payload.password)

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
    if payload.select_fields:
        from urllib.parse import quote
        odata_url += f"&$select={quote(','.join(payload.select_fields), safe=',')}"

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
        raise HTTPException(status_code=502, detail=f"HES API error: {e}")

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
        action="hes_ingest",
        details=(f"Smart Meter HES {entity} → {payload.namespace}.{payload.table_name}: "
                 f"{len(records)} rows via {payload.auth_type}"),
        status="success"
    )

    return {
        "status": "success",
        "message": (f"Successfully ingested {len(records):,} records from HES entity '{entity}' "
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
    from tenancy import get_current_tenant_id, scope_namespace
    stats = get_graph_stats(scope_namespace(get_current_tenant_id(user), graph_name))
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
    from tenancy import get_current_tenant_id, scope_namespace
    try:
        df = execute_cypher_query(scope_namespace(get_current_tenant_id(user), payload.graph_name), payload.query)
        
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


# ─── DQE Pydantic request models (defined here, directly, not as string
# forward-references) ────────────────────────────────────────────────────
# FastAPI decides how to parse each parameter (as a JSON body vs. a query
# param) once, at route-registration time, using whatever type it can
# resolve at that exact moment. A string annotation like payload: "Foo"
# only resolves if `Foo` is already a name in this module's namespace when
# the @app.post(...) decorator runs. These classes must therefore be
# defined and directly referenced (no quotes) BEFORE the routes below.
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


@app.post("/v1/query/submit", tags=["Query Engine"])
async def dqe_submit(
    payload: _DQESubmitRequest,
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
    from tenancy import get_current_tenant_id

    if user.get("role", "Business Analyst") in DASHBOARD_ONLY_ROLES:
        raise HTTPException(
            status_code=403,
            detail=f"Role '{user.get('role')}' is dashboard-only — use Catalog and Observability instead of ad-hoc queries."
        )

    if payload.mode == "python" and user.get("role", "Business Analyst") not in CAN_RUN_PYTHON:
        raise HTTPException(
            status_code=403,
            detail=f"Access Denied: Role '{user.get('role', 'Business Analyst')}' does not have permission to run Python extraction scripts."
        )

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
            role=user.get("role", "Business Analyst"),
            tenant_id=get_current_tenant_id(user),
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


@app.get("/v1/query/modes", tags=["Query Engine"])
async def dqe_modes(user: Dict[str, Any] = Depends(get_current_user)):
    """Return supported query modes, required fields, and example payloads."""
    engine = _get_query_engine()
    return {"modes": engine.supported_modes()}


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


# NOTE: /v1/query/{job_id} must be registered AFTER every other static
# /v1/query/<literal> route above (modes, history) — Starlette matches routes
# in registration order, so a static route registered after this catch-all
# would be shadowed by it (e.g. GET /v1/query/modes would be swallowed as a
# job-id lookup for job "modes" and incorrectly 404).
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
    payload: _DQEExplainRequest,
    user: Dict[str, Any] = Depends(get_current_user),
):
    """
    Dry-run: return the execution plan for a query without executing it.

    Validates syntax and returns routing information, EXPLAIN text (for SQL),
    and graph statistics (for Graph mode). Does not consume compute resources.
    """
    from query_engine.models import QueryJob, QueryMode, QueryExplainRequest as _QER
    from tenancy import get_current_tenant_id

    try:
        # SEC-2026-002: /query/explain loads and registers the real table
        # (SQLExecutor.explain -> _load_iceberg), so it is a data-touching
        # path and must carry tenant + role like every other job.
        job = QueryJob(
            mode=QueryMode(payload.mode),
            namespace=payload.namespace,
            table_name=payload.table_name,
            sql=payload.sql,
            cypher=payload.cypher,
            graph_name=payload.graph_name,
            python_script=payload.python_script,
            role=user.get("role", "Business Analyst"),
            tenant_id=get_current_tenant_id(user),
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    engine = _get_query_engine()
    plan = engine.explain(job)
    return {"mode": payload.mode, "execution_plan": plan}


@app.post("/v1/query/multi", tags=["Query Engine"])
async def dqe_multi(
    payload: _DQEMultiRequest,
    user: Dict[str, Any] = Depends(get_current_user),
):
    """
    Fan-out multiple queries across any mix of SQL / Graph / Python modes.

    Results are returned as individual job results. When merge_strategy='union',
    all result rows are concatenated into a single merged_result (requires
    identical column schemas). Use join_on_key for key-based merging.
    """
    from query_engine.models import QueryJob, QueryMode, MultiQueryRequest as _MQR
    from tenancy import get_current_tenant_id
    import asyncio as _asyncio

    if user.get("role", "Business Analyst") in DASHBOARD_ONLY_ROLES:
        raise HTTPException(
            status_code=403,
            detail=f"Role '{user.get('role')}' is dashboard-only — use Catalog and Observability instead of ad-hoc queries."
        )

    if len(payload.queries) > 10:
        raise HTTPException(status_code=400, detail="Maximum 10 queries per multi-request.")

    if any(q.mode == "python" for q in payload.queries) and user.get("role", "Business Analyst") not in CAN_RUN_PYTHON:
        raise HTTPException(
            status_code=403,
            detail=f"Access Denied: Role '{user.get('role', 'Business Analyst')}' does not have permission to run Python extraction scripts."
        )

    tenant_id = get_current_tenant_id(user)
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
                role=user.get("role", "Business Analyst"),
                tenant_id=tenant_id,
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


# ── Quantum & AI/ML Optimization Endpoints ───────────────────────────────────

class _QuantumQuboRequest(BaseModel):
    graph_name: Optional[str] = "main"
    nodes: Optional[List[str]] = None
    edges: Optional[List[List[Any]]] = None
    sweeps: int = 400

class _AIEmbedRequest(BaseModel):
    graph_name: Optional[str] = "main"
    dimensions: int = 16
    metric: Optional[str] = "adamic_adar"

@app.post("/v1/quantum/qubo-solve", tags=["Quantum Engine"])
async def quantum_qubo_solve(
    payload: _QuantumQuboRequest,
    user: Dict[str, Any] = Depends(get_current_user),
):
    """
    Solves combinatorial graph clustering & partitioning using the Quantum-Inspired
    Simulated Annealer (QISA) and generates QAOA OpenQASM quantum circuits.
    """
    from query_engine.quantum_optimizer import QuantumOptimizer
    import networkx as nx

    G = nx.Graph()
    if payload.nodes and payload.edges:
        G.add_nodes_from(payload.nodes)
        for e in payload.edges:
            if len(e) >= 2:
                w = float(e[2]) if len(e) >= 3 else 1.0
                G.add_edge(e[0], e[1], weight=w)
    else:
        from graph_db import load_networkx_graph
        try:
            G = load_networkx_graph(payload.graph_name).to_undirected()
        except Exception:
            G = nx.cycle_graph(6)

    res = QuantumOptimizer.partition_graph_quantum(G, sweeps=payload.sweeps)
    return res


@app.post("/v1/ai/graph-embeddings", tags=["AI Engine"])
async def ai_graph_embeddings(
    payload: _AIEmbedRequest,
    user: Dict[str, Any] = Depends(get_current_user),
):
    """
    Generates topological node embeddings using random walks and spectral projections.
    """
    from query_engine.ai_ml_engine import AIMLEngine
    from graph_db import load_networkx_graph
    import networkx as nx
    try:
        G = load_networkx_graph(payload.graph_name)
    except Exception:
        G = nx.path_graph(10, create_using=nx.DiGraph)

    embeddings = AIMLEngine.generate_node_embeddings(G, dimensions=payload.dimensions)
    return {"total_nodes": len(embeddings), "dimensions": payload.dimensions, "embeddings": embeddings}


@app.post("/v1/ai/link-prediction", tags=["AI Engine"])
async def ai_link_prediction(
    payload: _AIEmbedRequest,
    user: Dict[str, Any] = Depends(get_current_user),
):
    """
    Predicts high-probability candidate links/relationships in the graph store.
    """
    from query_engine.ai_ml_engine import AIMLEngine
    from graph_db import load_networkx_graph
    import networkx as nx
    try:
        G = load_networkx_graph(payload.graph_name)
    except Exception:
        G = nx.path_graph(10, create_using=nx.DiGraph)

    links = AIMLEngine.predict_links(G, top_k=20, metric=payload.metric or "adamic_adar")
    return {"predicted_links": links, "metric": payload.metric}


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
    from tenancy import get_current_tenant_id, filter_and_unscope_namespaces, scope_namespace
    try:
        tenant_id = get_current_tenant_id(user)
        m_catalog = MeldraCatalog()
        all_namespaces = m_catalog.catalog.list_namespaces()
        all_namespaces = [ns[0] if isinstance(ns, tuple) else ns for ns in all_namespaces]
        visible = filter_and_unscope_namespaces(tenant_id, all_namespaces)
        if not visible:
            # First namespace for a brand-new tenant — create their own
            # scoped "default", never a bare shared one.
            m_catalog.create_namespace(scope_namespace(tenant_id, "default"))
            visible = ["default"]
        return {"namespaces": visible}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/v1/catalog/namespaces", tags=["Catalog"])
async def create_namespace(payload: CreateNamespaceRequest, user: Dict[str, Any] = Depends(get_current_user)):
    from meldra import MeldraCatalog
    from tenancy import get_current_tenant_id, scope_namespace
    tenant_id = get_current_tenant_id(user)
    scoped_ns = scope_namespace(tenant_id, payload.namespace)
    try:
        m_catalog = MeldraCatalog()
        m_catalog.create_namespace(scoped_ns)
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
    if role not in CAN_MANAGE_SCHEMA:
        raise HTTPException(status_code=403, detail=f"Access Denied: Role '{role}' does not have permission to delete namespaces.")
    from meldra import MeldraCatalog
    from tenancy import get_current_tenant_id, scope_namespace
    tenant_id = get_current_tenant_id(user)
    scoped_ns = scope_namespace(tenant_id, namespace)
    try:
        m_catalog = MeldraCatalog()
        m_catalog.delete_namespace(scoped_ns)
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
    from tenancy import get_current_tenant_id, scope_namespace
    tenant_id = get_current_tenant_id(user)
    try:
        m_catalog = MeldraCatalog()
        tables = m_catalog.list_tables(scope_namespace(tenant_id, namespace))
        return {"tables": tables}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/v1/catalog/namespaces/{namespace}/tables/{table_name}", tags=["Catalog"])
async def get_table_details(namespace: str, table_name: str, user: Dict[str, Any] = Depends(get_current_user)):
    from meldra import MeldraCatalog
    from tenancy import get_current_tenant_id, scope_namespace
    tenant_id = get_current_tenant_id(user)
    try:
        m_catalog = MeldraCatalog()
        details = m_catalog.get_table_details(scope_namespace(tenant_id, namespace), table_name)
        details["namespace"] = namespace  # report back the client-facing (unscoped) name
        return details
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/v1/catalog/namespaces/{namespace}/tables/{table_name}/schema", tags=["Catalog"])
async def evolve_schema(namespace: str, table_name: str, payload: SchemaEvolutionRequest, user: Dict[str, Any] = Depends(get_current_user)):
    role = user.get("role", "Business Analyst")
    if role not in CAN_MANAGE_SCHEMA:
        raise HTTPException(status_code=403, detail=f"Access Denied: Role '{role}' does not have permission to evolve schemas.")
    from meldra import MeldraCatalog
    from tenancy import get_current_tenant_id, scope_namespace
    tenant_id = get_current_tenant_id(user)
    try:
        m_catalog = MeldraCatalog()
        actions_list = [act.dict() for act in payload.actions]
        m_catalog.evolve_schema(scope_namespace(tenant_id, namespace), table_name, actions_list)
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
    if user.get("role", "Business Analyst") not in CAN_INGEST:
        raise HTTPException(
            status_code=403,
            detail=f"Access Denied: Role '{user.get('role')}' does not have permission to ingest data."
        )
    from meldra import MeldraCatalog, MeldraValidator
    from tenancy import get_current_tenant_id, scope_namespace
    import pyarrow as pa

    payload.namespace = scope_namespace(get_current_tenant_id(user), payload.namespace)
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
    if user.get("role", "Business Analyst") in DASHBOARD_ONLY_ROLES:
        raise HTTPException(
            status_code=403,
            detail=f"Role '{user.get('role')}' is dashboard-only — use Catalog and Observability instead of ad-hoc queries."
        )
    from meldra import MeldraCatalog
    from tenancy import get_current_tenant_id, scope_namespace
    import duckdb
    tenant_id = get_current_tenant_id(user)
    client_namespace = payload.namespace          # display name, used for RBAC policy matching
    scoped_namespace = scope_namespace(tenant_id, payload.namespace)  # real catalog namespace
    try:
        m_catalog = MeldraCatalog()
        tables = m_catalog.list_tables(scoped_namespace)

        # Restrict SQL capabilities for secure query execution
        sql_upper = payload.sql.upper()
        forbidden_keywords = ["ATTACH", "COPY", "INSTALL", "LOAD"]
        for kw in forbidden_keywords:
            if kw in sql_upper:
                raise Exception(f"SQL execution denied: Keyword '{kw}' is blocked for security.")

        con = duckdb.connect(database=':memory:')
        con.execute("SET enable_external_access=false;")

        # Apply full RBAC (table access, row filtering, column masking/denial)
        # at the data layer, BEFORE registering with DuckDB — so no amount of
        # aliasing/subquerying in the SQL can expose the real values or the
        # existence of a table this role can't see. See rbac_utils.enforce_rbac.
        # A table this role has no access to is simply never registered — it
        # fails as "table not found" rather than confirming it exists.
        from rbac_utils import enforce_rbac
        role = user.get("role", "Business Analyst")

        for tbl_name in tables:
            try:
                # Time travel scan (tenant-scoped namespace for the actual
                # catalog read, display namespace for RBAC policy matching)
                arrow_tbl = m_catalog.run_time_travel_scan(scoped_namespace, tbl_name, payload.snapshot_id)
                tbl_df = enforce_rbac(arrow_tbl.to_pandas(), client_namespace, tbl_name, role)
                con.register(tbl_name, tbl_df)
            except Exception:
                pass

        start_time = time.time()
        result_df = con.execute(payload.sql).fetchdf()
        duration_ms = (time.time() - start_time) * 1000

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
    from tenancy import get_current_tenant_id, scope_namespace
    tenant_id = get_current_tenant_id(user)
    scoped_ns = scope_namespace(tenant_id, namespace)
    try:
        m_catalog = MeldraCatalog()
        if payload.action == "optimize":
            msg = m_catalog.optimize_table(scoped_ns, table_name)
        elif payload.action == "expire_snapshots":
            msg = m_catalog.expire_snapshots(scoped_ns, table_name)
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
    from tenancy import get_current_tenant_id, scope_namespace
    import json
    tenant_id = get_current_tenant_id(user)
    try:
        m_catalog = MeldraCatalog()
        catalog = m_catalog.catalog
        identifier = (scope_namespace(tenant_id, namespace), table_name)
        table = catalog.load_table(identifier)
        contract_json = json.dumps(payload.rules)
        table.transaction().set_properties({"data_contracts": contract_json}).commit()
        return {"status": "success", "message": "Data contracts updated."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/v1/catalog/namespaces/{namespace}/tables/{table_name}/contracts", tags=["Catalog"])
async def get_data_contracts(namespace: str, table_name: str, user: Dict[str, Any] = Depends(get_current_user)):
    from meldra import MeldraCatalog
    from tenancy import get_current_tenant_id, scope_namespace
    import json
    tenant_id = get_current_tenant_id(user)
    try:
        m_catalog = MeldraCatalog()
        catalog = m_catalog.catalog
        identifier = (scope_namespace(tenant_id, namespace), table_name)
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
    from tenancy import get_current_tenant_id, scope_namespace
    tenant_id = get_current_tenant_id(user)
    try:
        catalog = get_catalog()
        table_identifier = f"{scope_namespace(tenant_id, req.namespace)}.{req.table_name}"
        table = catalog.load_table(table_identifier)
        df = table.scan().to_arrow().to_pandas()

        if req.source_col not in df.columns or req.target_col not in df.columns:
            raise HTTPException(
                status_code=400,
                detail=f"Source column '{req.source_col}' or Target column '{req.target_col}' not found in table schema."
            )

        result = sync_dataframe_to_neo4j(
            graph_name=scope_namespace(tenant_id, req.graph_name),
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
    """
    Reset the CALLING TENANT's own data only. Previously this deleted every
    other user's account platform-wide plus all RBAC policies and audit
    logs globally — safe with a single shared tenant, catastrophic once
    there's more than one, since any user's own Admin role let them wipe
    every other tenant's account and data. Now scoped to: this tenant's own
    Iceberg namespaces and this tenant's own graph nodes/edges. Other
    accounts, global RBAC config, and the audit trail (kept for compliance
    history, including across a reset) are untouched.
    """
    role = user.get("role", "Business Analyst")
    if role != "Admin":
        raise HTTPException(
            status_code=403,
            detail="Access Denied: Only users with the 'Admin' role can reset their tenant."
        )

    from auth_db import _get_conn
    from catalog_setup import get_catalog
    from tenancy import get_current_tenant_id, tenant_prefix

    tenant_id = get_current_tenant_id(user)
    prefix = tenant_prefix(tenant_id)

    # 1. Clear this tenant's own graph data only
    conn = _get_conn()
    try:
        cur = conn.cursor()
        cur.execute("DELETE FROM auth.graph_nodes WHERE workspace_id LIKE %s;", (f"{prefix}%",))
        cur.execute("DELETE FROM auth.graph_edges WHERE workspace_id LIKE %s;", (f"{prefix}%",))
        conn.commit()
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=f"Database reset error: {str(e)}")
    finally:
        conn.close()

    # 2. Drop this tenant's own Iceberg tables/namespaces only
    dropped = 0
    try:
        catalog = get_catalog()
        for full_ns in catalog.list_namespaces():
            full_ns_name = full_ns[0] if isinstance(full_ns, tuple) else full_ns
            if not full_ns_name.startswith(prefix):
                continue
            for t_ident in catalog.list_tables(full_ns_name):
                try:
                    catalog.drop_table(t_ident)
                    dropped += 1
                except Exception:
                    pass
    except Exception as e:
        print(f"[reset-tenant] Failed to drop catalog tables: {e}")

    log_audit(
        user_id=user.get("sub", "unknown"),
        tier=user.get("tier", "trial"),
        action="reset_tenant",
        details=f"Reset own tenant: dropped {dropped} table(s) and this tenant's graph data.",
        status="success"
    )

    return {"status": "success", "message": f"Your tenant has been reset: {dropped} table(s) dropped."}


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

class RowFilterItem(BaseModel):
    role: str
    namespace: str
    table_name: str          # or "*" for every table in the namespace
    filter_expression: str   # pandas .query() expression, e.g. "region == 'EMEA'"
    description: Optional[str] = None

class SaveRowFiltersRequest(BaseModel):
    filters: List[RowFilterItem]

@app.get("/v1/rbac/policies", tags=["RBAC"])
async def get_rbac_policies(user: Dict[str, Any] = Depends(get_current_user)):
    if user.get("role", "Business Analyst") not in CAN_MANAGE_RBAC:
        raise HTTPException(status_code=403, detail="Only Admins can view RBAC policies.")
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
    if role not in CAN_MANAGE_RBAC:
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

@app.get("/v1/rbac/row-filters", tags=["RBAC"])
async def get_row_filters(user: Dict[str, Any] = Depends(get_current_user)):
    if user.get("role", "Business Analyst") not in CAN_MANAGE_RBAC:
        raise HTTPException(status_code=403, detail="Only Admins can view row-level filters.")
    from auth_db import _get_conn
    conn = _get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT id, role, namespace, table_name, filter_expression, description, created_at "
            "FROM auth.rbac_row_filters ORDER BY created_at DESC;"
        )
        rows = cur.fetchall()
        return [
            {**dict(r), "created_at": r["created_at"].isoformat() if r["created_at"] else None}
            for r in rows
        ]
    finally:
        conn.close()

@app.post("/v1/rbac/row-filters", tags=["RBAC"])
async def save_row_filters(payload: SaveRowFiltersRequest, user: Dict[str, Any] = Depends(get_current_user)):
    role = user.get("role", "Business Analyst")
    if role not in CAN_MANAGE_RBAC:
        raise HTTPException(status_code=403, detail="Only Admins can modify row-level filters.")
    from auth_db import _get_conn
    conn = _get_conn()
    try:
        cur = conn.cursor()
        cur.execute("DELETE FROM auth.rbac_row_filters;")
        for item in payload.filters:
            cur.execute("""
                INSERT INTO auth.rbac_row_filters (role, namespace, table_name, filter_expression, description)
                VALUES (%s, %s, %s, %s, %s);
            """, (item.role, item.namespace, item.table_name, item.filter_expression, item.description))
        conn.commit()
        log_audit(
            user_id=user.get("sub", "unknown"),
            tier=user.get("tier", "trial"),
            action="save_row_filters",
            details=f"Replaced row-level filter set ({len(payload.filters)} filters)",
            status="success"
        )
        return {"status": "success", "message": "Row-level filters updated."}
    finally:
        conn.close()

@app.post("/v1/rbac/user-role", tags=["RBAC"])
async def update_user_role(payload: UpdateUserRoleRequest, user: Dict[str, Any] = Depends(get_current_user)):
    role = user.get("role", "Business Analyst")
    if role not in CAN_MANAGE_RBAC:
        raise HTTPException(status_code=403, detail="Only Admins can modify user roles.")

    if payload.role not in ALL_ROLES:
        raise HTTPException(
            status_code=422,
            detail=f"'{payload.role}' is not a recognised role. Valid roles: {', '.join(ALL_ROLES)}."
        )
    from auth_db import _get_conn
    conn = _get_conn()
    try:
        cur = conn.cursor()
        cur.execute("UPDATE auth.users SET user_role = %s WHERE email = %s;", (payload.role, payload.email.lower().strip()))
        conn.commit()
        return {"status": "success", "message": f"User {payload.email} role updated to {payload.role}."}
    finally:
        conn.close()

@app.get("/v1/rbac/roles", tags=["RBAC"])
async def list_roles(user: Dict[str, Any] = Depends(get_current_user)):
    """
    All personas the platform recognises, with a one-line description of
    what each can do — lets the frontend render a real role picker (for
    Admins assigning roles) instead of a hardcoded list that drifts from
    roles.py. Available to any authenticated user since it's just naming
    the personas, not granting anything.
    """
    return {
        "roles": [
            {"name": r, "description": ROLE_DESCRIPTIONS[r]}
            for r in ALL_ROLES
        ]
    }


# ─────────────────────────────────────────
# APPROVER DESIGNATION + PROMOTIONS
# Real backend enforcement for "Promote to Production" — replaces a UI
# that previously accepted any typed string as a signature and never
# called the server at all. Approver is a designation an Admin grants to
# specific users, independent of role/persona (see set_user_approver).
# ─────────────────────────────────────────

class SetApproverRequest(BaseModel):
    email: EmailStr
    is_approver: bool

class CreatePromotionRequest(BaseModel):
    pipeline_name: str
    environment: str  # 'staging' | 'production'
    version_ref: str
    notes: Optional[str] = None

    @field_validator("environment")
    @classmethod
    def _valid_env(cls, v: str) -> str:
        if v not in ("staging", "production"):
            raise ValueError("environment must be 'staging' or 'production'")
        return v

class DecidePromotionRequest(BaseModel):
    approve: bool
    decision_notes: Optional[str] = None


@app.post("/v1/rbac/user-approver", tags=["RBAC"])
async def update_user_approver(payload: SetApproverRequest, user: Dict[str, Any] = Depends(get_current_user)):
    """Admin-only: grant or revoke the Approver designation for a user.
    Independent of role — an Approver can be a Data Architect, a Business
    Analyst, whoever the Admin trusts to gate production promotions."""
    if user.get("role", "Business Analyst") not in CAN_MANAGE_RBAC:
        raise HTTPException(status_code=403, detail="Only Admins can manage the Approver designation.")
    set_user_approver(payload.email, payload.is_approver)
    log_audit(
        user_id=user.get("sub", "unknown"),
        tier=user.get("tier", "trial"),
        action="set_user_approver",
        details=f"{'Granted' if payload.is_approver else 'Revoked'} Approver for {payload.email}",
        status="success",
    )
    return {"status": "success", "message": f"{payload.email} {'is now' if payload.is_approver else 'is no longer'} an Approver."}


@app.get("/v1/rbac/approvers", tags=["RBAC"])
async def get_approvers(user: Dict[str, Any] = Depends(get_current_user)):
    if user.get("role", "Business Analyst") not in CAN_MANAGE_RBAC:
        raise HTTPException(status_code=403, detail="Only Admins can view the Approver list.")
    return {"approvers": list_approvers()}


@app.get("/v1/admin/users", tags=["RBAC"])
async def get_all_users(user: Dict[str, Any] = Depends(get_current_user)):
    """
    Every registered user, for the Admin's User & Role Management page.
    This is the piece that was actually missing before: role assignment
    (update_user_role below) had no way to discover who exists to assign
    a role to, short of already knowing someone's exact email address.
    """
    if user.get("role", "Business Analyst") not in CAN_MANAGE_RBAC:
        raise HTTPException(status_code=403, detail="Only Admins can view the user directory.")
    users = list_all_users()
    return {
        "users": [
            {
                "id": str(u["id"]),
                "email": u["email"],
                "role": u.get("user_role", "Business Analyst"),
                "is_approver": bool(u.get("is_approver", False)),
                "is_verified": bool(u.get("is_verified", False)),
                "is_active": bool(u.get("is_active", True)),
                "created_at": _safe_iso(u.get("created_at")),
                "last_login_at": _safe_iso(u.get("last_login_at")),
            }
            for u in users
        ]
    }


@app.post("/v1/promotions", tags=["Promotions"])
async def submit_promotion(payload: CreatePromotionRequest, user: Dict[str, Any] = Depends(get_current_user)):
    """
    Staging promotions deploy immediately (no gate). Production promotions
    are recorded as 'pending' and sit there until a different user who is
    a designated Approver calls /v1/promotions/{id}/decide — see
    decide_promotion below for the actual enforcement.
    """
    from tenancy import get_current_tenant_id
    tenant_id = get_current_tenant_id(user)
    promo = create_promotion(
        tenant_id=tenant_id,
        pipeline_name=payload.pipeline_name,
        environment=payload.environment,
        version_ref=payload.version_ref,
        requested_by=user["sub"],
        notes=payload.notes,
    )
    log_audit(
        user_id=user.get("sub", "unknown"),
        tier=user.get("tier", "trial"),
        action="request_promotion",
        details=f"{payload.pipeline_name} -> {payload.environment} ({payload.version_ref}) — status={promo['status']}",
        status="success",
    )
    return promo


@app.get("/v1/promotions", tags=["Promotions"])
async def get_promotions(user: Dict[str, Any] = Depends(get_current_user)):
    """
    Designated Approvers see pending promotions across every account —
    there's no org/team concept in this platform (tenancy.py: one tenant =
    one account), so an Approver reviewing someone else's request is
    inherently cross-tenant. Everyone else sees only their own.
    """
    from tenancy import get_current_tenant_id
    viewer = get_user_by_id(user["sub"])
    if viewer and viewer.get("is_approver"):
        return {"promotions": list_promotions(None)}
    return {"promotions": list_promotions(get_current_tenant_id(user))}


@app.post("/v1/promotions/{promotion_id}/decide", tags=["Promotions"])
async def decide_promotion_endpoint(promotion_id: int, payload: DecidePromotionRequest, user: Dict[str, Any] = Depends(get_current_user)):
    """
    Real four-eyes enforcement:
      1. The decider must currently be a designated Approver (checked fresh
         against the database, not a JWT claim — a revoked Approver's
         existing access token must not still work).
      2. The decider cannot be the same person who requested the promotion.
      3. The promotion must still be 'pending' (no deciding twice).

    Deliberately NOT tenant-scoped: this platform has no org/team concept
    (tenancy.py — one tenant = one account), so the requester and their
    Approver are never in the same tenant by definition. Approver is a
    cross-cutting designation an Admin grants to a trusted reviewer,
    analogous to Admin's own cross-cutting authority elsewhere.
    """
    promo = get_promotion(promotion_id)
    if promo is None:
        raise HTTPException(status_code=404, detail="Promotion request not found.")

    if promo["status"] != "pending":
        raise HTTPException(status_code=409, detail=f"This promotion is already '{promo['status']}' — it can't be decided again.")

    decider = get_user_by_id(user["sub"])
    if not decider or not decider.get("is_approver"):
        raise HTTPException(status_code=403, detail="Only a designated Approver can approve or reject a production promotion.")

    if str(promo["requested_by"]) == str(user["sub"]):
        raise HTTPException(status_code=403, detail="You cannot approve your own promotion request — a different Approver must review it.")

    decided = decide_promotion(promotion_id, decided_by=user["sub"], approve=payload.approve, decision_notes=payload.decision_notes)
    log_audit(
        user_id=user.get("sub", "unknown"),
        tier=user.get("tier", "trial"),
        action="decide_promotion",
        details=f"Promotion #{promotion_id} ({promo['pipeline_name']} -> {promo['environment']}) {'approved' if payload.approve else 'rejected'}",
        status="success",
    )
    return decided

@app.get("/v1/studio/search", tags=["Studio"])
async def search_studio(q: str, user: Dict[str, Any] = Depends(get_current_user)):
    from meldra import MeldraCatalog
    query = q.lower().strip()
    results = []
    
    # Kept in sync with the real sidebar nav ids in index.html
    # (frontend/vite-project/index.html's #nav-* buttons) — this used to
    # list pages that don't exist (a "Learn Academy" with no page behind it
    # at all) and stale routes (chat-tab used to be the chat console; it's
    # the Home dashboard now, with chat split out to assistant-tab).
    pages = [
        {"name": "Home", "type": "page", "route": "chat-tab", "desc": "Lakehouse overview — tables, connection status, recent activity"},
        {"name": "Assistant", "type": "page", "route": "assistant-tab", "desc": "Chat with your data lake using AI"},
        {"name": "Ingest", "type": "page", "route": "ingest-tab", "desc": "Upload CSV, enterprise connectors, or sample datasets"},
        {"name": "Graph", "type": "page", "route": "graph-tab", "desc": "Run openCypher queries on Apache AGE"},
        {"name": "Workspace", "type": "page", "route": "workspace-tab", "desc": "Connect your own S3 data lake bucket"},
        {"name": "Data Studio", "type": "page", "route": "studio-tab", "desc": "SQL console, Python workspace, schema evolution, RBAC policies, pipelines"},
        {"name": "Query Lab", "type": "page", "route": "query-lab-tab", "desc": "Distributed query engine — SQL, graph, Python"},
        {"name": "Audit", "type": "page", "route": "audit-tab", "desc": "Real audit trail of every auth and data operation"},
        {"name": "MCP Gateway", "type": "page", "route": "mcp-tab", "desc": "Real MCP server tools for external clients"},
        {"name": "API Docs", "type": "page", "route": "api-tab", "desc": "REST API reference"},
        {"name": "Observability", "type": "page", "route": "traffic-tab", "desc": "Query traffic, cost and platform health"},
    ]
    for p in pages:
        if query in p["name"].lower() or query in p["desc"].lower():
            results.append(p)
            
    try:
        from tenancy import get_current_tenant_id, filter_and_unscope_namespaces, scope_namespace
        tenant_id = get_current_tenant_id(user)
        m_catalog = MeldraCatalog()
        all_namespaces = m_catalog.catalog.list_namespaces()
        all_namespaces = [ns[0] if isinstance(ns, tuple) else ns for ns in all_namespaces]
        # Only this tenant's own namespaces/tables can show up in search --
        # otherwise search would leak every tenant's namespace/table names
        # to anyone typing in the search box.
        namespaces = filter_and_unscope_namespaces(tenant_id, all_namespaces)
        for ns in namespaces:
            if query in ns.lower():
                results.append({"name": f"Namespace '{ns}'", "type": "namespace", "route": "studio-tab", "desc": f"Iceberg catalog namespace"})

            tables = m_catalog.list_tables(scope_namespace(tenant_id, ns))
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
        
    # Search transaction records inside default.transactions_10k table if it exists
    try:
        table = m_catalog.load_table("default.transactions_10k")
        arrow_table = table.scan().to_arrow()
        
        import duckdb
        con = duckdb.connect(database=':memory:')
        con.execute("SET enable_external_access=false;")
        con.register("tx_table", arrow_table)
        
        # Look for matching ID or accounts (up to 5 results to keep search fast and relevant)
        sql_query = f"""
            SELECT tx_id, account_from, account_to, amount, status, timestamp 
            FROM tx_table 
            WHERE CAST(tx_id AS VARCHAR) LIKE '%{query}%'
               OR LOWER(account_from) LIKE '%{query}%'
               OR LOWER(account_to) LIKE '%{query}%'
               OR LOWER(status) LIKE '%{query}%'
            LIMIT 5
        """
        db_results = con.execute(sql_query).fetchall()
        for row in db_results:
            tx_id, acc_from, acc_to, amt, status, ts = row
            results.append({
                "name": f"Transaction #{tx_id}",
                "type": "transaction",
                "route": "studio-tab",
                "desc": f"{acc_from} ➔ {acc_to} | ${amt} ({status})",
                "tx_id": tx_id,
                "account_from": acc_from,
                "account_to": acc_to,
                "amount": amt,
                "status": status,
                "timestamp": ts
            })
    except Exception as e:
        print(f"[search] Error searching transactions: {e}")

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
