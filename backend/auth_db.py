# Copyright (c) 2025 Meldra AI Ltd. All rights reserved.
# This software is proprietary and confidential. Unauthorised use is prohibited.
"""
auth_db.py — PostgreSQL authentication database layer
Uses the same Postgres instance as Apache AGE (GRAPH_DB_* env vars).
Creates an `auth` schema with tables for users, sessions, mfa_tokens, and audit_logs.
"""
from __future__ import annotations

import os
import hashlib
import secrets
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
import bcrypt
import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

load_dotenv()

# ─────────────────────────────────────────
# DB CONNECTION
# ─────────────────────────────────────────
def _get_conn():
    return psycopg2.connect(
        host=os.environ.get("GRAPH_DB_HOST", "localhost"),
        port=int(os.environ.get("GRAPH_DB_PORT", 5432)),
        user=os.environ.get("GRAPH_DB_USER", "postgres"),
        password=os.environ.get("GRAPH_DB_PASSWORD", ""),
        dbname=os.environ.get("GRAPH_DB_NAME", "graphdb"),
        cursor_factory=psycopg2.extras.RealDictCursor,
    )

# ─────────────────────────────────────────
# PASSWORD HASHING (Direct bcrypt implementation)
# ─────────────────────────────────────────
def hash_password(plain: str) -> str:
    password_bytes = plain.encode('utf-8')
    hashed_bytes = bcrypt.hashpw(password_bytes, bcrypt.gensalt())
    return hashed_bytes.decode('utf-8')

def verify_password(plain: str, hashed: str) -> bool:
    try:
        password_bytes = plain.encode('utf-8')
        hashed_bytes = hashed.encode('utf-8')
        return bcrypt.checkpw(password_bytes, hashed_bytes)
    except Exception:
        return False

# ─────────────────────────────────────────
# SCHEMA INIT
# ─────────────────────────────────────────
def init_auth_schema():
    """Create auth schema and all tables. Called on FastAPI startup."""
    conn = _get_conn()
    try:
        cur = conn.cursor()

        cur.execute("CREATE SCHEMA IF NOT EXISTS auth;")

        cur.execute("""
            CREATE TABLE IF NOT EXISTS auth.users (
                id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                email           TEXT UNIQUE NOT NULL,
                password_hash   TEXT NOT NULL,
                mfa_method      TEXT NOT NULL DEFAULT 'email',  -- 'email' or 'phone'
                phone           TEXT,
                is_verified     BOOLEAN NOT NULL DEFAULT FALSE,
                is_active       BOOLEAN NOT NULL DEFAULT TRUE,
                created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                last_login_at   TIMESTAMPTZ,
                tier            TEXT NOT NULL DEFAULT 'trial',  -- 'trial' | 'sole_user' | 'single_user' | 'enterprise'
                expires_at      TIMESTAMPTZ,                   -- Expiration timestamp for trial accounts
                reg_ip          TEXT,                          -- Registration IP address
                reg_country     TEXT,                          -- Registration Geography / Country
                subscription_status TEXT NOT NULL DEFAULT 'active' -- 'active' | 'expired' | 'canceled'
            );
        """)

        # Run database migrations for existing tables in Neon automatically
        cur.execute("ALTER TABLE auth.users ADD COLUMN IF NOT EXISTS tier TEXT NOT NULL DEFAULT 'trial';")
        cur.execute("ALTER TABLE auth.users ADD COLUMN IF NOT EXISTS expires_at TIMESTAMPTZ;")
        cur.execute("ALTER TABLE auth.users ADD COLUMN IF NOT EXISTS reg_ip TEXT;")
        cur.execute("ALTER TABLE auth.users ADD COLUMN IF NOT EXISTS reg_country TEXT;")
        cur.execute("ALTER TABLE auth.users ADD COLUMN IF NOT EXISTS subscription_status TEXT NOT NULL DEFAULT 'active';")

        cur.execute("""
            CREATE TABLE IF NOT EXISTS auth.mfa_tokens (
                id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                user_id         UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
                token_hash      TEXT NOT NULL,
                purpose         TEXT NOT NULL DEFAULT 'login',  -- 'login' | 'register' | 'reset'
                attempts        INTEGER NOT NULL DEFAULT 0,
                expires_at      TIMESTAMPTZ NOT NULL,
                used            BOOLEAN NOT NULL DEFAULT FALSE,
                created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS auth.sessions (
                id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                user_id         UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
                refresh_token_hash TEXT NOT NULL,
                expires_at      TIMESTAMPTZ NOT NULL,
                revoked         BOOLEAN NOT NULL DEFAULT FALSE,
                created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                last_used_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
        """)

        # Migrate audit logs from SQLite to Postgres
        cur.execute("""
            CREATE TABLE IF NOT EXISTS auth.audit_logs (
                id              BIGSERIAL PRIMARY KEY,
                timestamp       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                user_id         TEXT NOT NULL DEFAULT 'system',
                tier            TEXT NOT NULL DEFAULT 'free',
                action          TEXT NOT NULL,
                details         TEXT,
                status          TEXT NOT NULL DEFAULT 'success'
            );
        """)

        # Indexes for performance
        cur.execute("CREATE INDEX IF NOT EXISTS idx_mfa_user ON auth.mfa_tokens(user_id);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_sessions_user ON auth.sessions(user_id);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_audit_timestamp ON auth.audit_logs(timestamp DESC);")

        conn.commit()
        print("[auth_db] Auth schema initialised successfully with geo, membership and expiration parameters.")
    except Exception as e:
        conn.rollback()
        print(f"[auth_db] Schema init error: {e}")
        raise
    finally:
        conn.close()


# ─────────────────────────────────────────
# USER OPERATIONS
# ─────────────────────────────────────────
def create_user(
    email: str, 
    password: str, 
    mfa_method: str = "email", 
    phone: Optional[str] = None,
    tier: str = "trial",
    reg_ip: Optional[str] = None,
    reg_country: Optional[str] = None
) -> Dict[str, Any]:
    conn = _get_conn()
    try:
        cur = conn.cursor()
        pwd_hash = hash_password(password)
        
        # Calculate 30-day expiration for trial memberships
        expires_at = None
        if tier == "trial":
            expires_at = datetime.utcnow() + timedelta(days=30)
            
        cur.execute(
            """
            INSERT INTO auth.users (email, password_hash, mfa_method, phone, tier, expires_at, reg_ip, reg_country)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id, email, mfa_method, phone, is_verified, created_at, tier, expires_at, reg_ip, reg_country, subscription_status
            """,
            (email.lower().strip(), pwd_hash, mfa_method, phone, tier, expires_at, reg_ip, reg_country),
        )
        user = dict(cur.fetchone())
        conn.commit()
        return user
    except psycopg2.errors.UniqueViolation:
        conn.rollback()
        raise ValueError(f"Email {email} is already registered.")
    finally:
        conn.close()


def get_user_by_email(email: str) -> Optional[Dict[str, Any]]:
    conn = _get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM auth.users WHERE email = %s AND is_active = TRUE",
            (email.lower().strip(),),
        )
        row = cur.fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_user_by_id(user_id: str) -> Optional[Dict[str, Any]]:
    conn = _get_conn()
    try:
        cur = conn.cursor()
        cur.execute("SELECT * FROM auth.users WHERE id = %s", (user_id,))
        row = cur.fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def mark_user_verified(user_id: str):
    conn = _get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            "UPDATE auth.users SET is_verified = TRUE, last_login_at = NOW() WHERE id = %s",
            (user_id,),
        )
        conn.commit()
    finally:
        conn.close()


def update_last_login(user_id: str):
    conn = _get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            "UPDATE auth.users SET last_login_at = NOW() WHERE id = %s", (user_id,)
        )
        conn.commit()
    finally:
        conn.close()


# ─────────────────────────────────────────
# MFA TOKEN OPERATIONS
# ─────────────────────────────────────────
MFA_OTP_EXPIRE_MINUTES = 10
MFA_MAX_ATTEMPTS = 3


def _hash_code(code: str) -> str:
    return hashlib.sha256(code.encode()).hexdigest()


def generate_otp() -> str:
    """Returns a cryptographically secure 6-digit OTP string."""
    return str(secrets.randbelow(900000) + 100000)


def store_mfa_token(user_id: str, code: str, purpose: str = "login") -> str:
    """Store OTP hash in DB. Returns the raw code (to be sent via email)."""
    conn = _get_conn()
    try:
        cur = conn.cursor()
        # Expire any existing tokens for this user + purpose
        cur.execute(
            "UPDATE auth.mfa_tokens SET used = TRUE WHERE user_id = %s AND purpose = %s AND used = FALSE",
            (user_id, purpose),
        )
        expires_at = datetime.utcnow() + timedelta(minutes=MFA_OTP_EXPIRE_MINUTES)
        cur.execute(
            """
            INSERT INTO auth.mfa_tokens (user_id, token_hash, purpose, expires_at)
            VALUES (%s, %s, %s, %s)
            RETURNING id
            """,
            (user_id, _hash_code(code), purpose, expires_at),
        )
        token_id = str(cur.fetchone()["id"])
        conn.commit()
        return token_id
    finally:
        conn.close()


def verify_mfa_token(user_id: str, code: str, purpose: str = "login") -> bool:
    """
    Validate OTP. Returns True if valid. 
    Increments attempt counter and marks token used on success.
    Raises ValueError on too many attempts or expired token.
    """
    conn = _get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT id, token_hash, attempts, expires_at, used
            FROM auth.mfa_tokens
            WHERE user_id = %s AND purpose = %s AND used = FALSE
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (user_id, purpose),
        )
        row = cur.fetchone()
        if not row:
            raise ValueError("No active OTP found. Please request a new one.")

        if row["used"]:
            raise ValueError("OTP has already been used.")

        if datetime.utcnow() > row["expires_at"].replace(tzinfo=None):
            raise ValueError("OTP has expired. Please request a new one.")

        if row["attempts"] >= MFA_MAX_ATTEMPTS:
            raise ValueError("Too many incorrect attempts. Please request a new OTP.")

        if row["token_hash"] != _hash_code(code):
            # Increment attempt counter
            cur.execute(
                "UPDATE auth.mfa_tokens SET attempts = attempts + 1 WHERE id = %s",
                (row["id"],),
            )
            conn.commit()
            remaining = MFA_MAX_ATTEMPTS - row["attempts"] - 1
            raise ValueError(f"Incorrect OTP. {remaining} attempt(s) remaining.")

        # Valid — mark as used
        cur.execute(
            "UPDATE auth.mfa_tokens SET used = TRUE WHERE id = %s", (row["id"],)
        )
        conn.commit()
        return True
    finally:
        conn.close()


def can_resend_otp(user_id: str, purpose: str = "login") -> bool:
    """Rate limit: allow resend only if last OTP is > 60 seconds old."""
    conn = _get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT created_at FROM auth.mfa_tokens
            WHERE user_id = %s AND purpose = %s
            ORDER BY created_at DESC LIMIT 1
            """,
            (user_id, purpose),
        )
        row = cur.fetchone()
        if not row:
            return True
        elapsed = datetime.utcnow() - row["created_at"].replace(tzinfo=None)
        return elapsed.total_seconds() >= 60
    finally:
        conn.close()


# ─────────────────────────────────────────
# SESSION OPERATIONS (Refresh Tokens)
# ─────────────────────────────────────────
REFRESH_TOKEN_EXPIRE_DAYS = 7


def create_session(user_id: str) -> str:
    """Creates a refresh token session. Returns the raw refresh token."""
    raw_token = secrets.token_urlsafe(48)
    conn = _get_conn()
    try:
        cur = conn.cursor()
        expires_at = datetime.utcnow() + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
        cur.execute(
            """
            INSERT INTO auth.sessions (user_id, refresh_token_hash, expires_at)
            VALUES (%s, %s, %s)
            """,
            (user_id, _hash_code(raw_token), expires_at),
        )
        conn.commit()
        return raw_token
    finally:
        conn.close()


def validate_refresh_token(raw_token: str) -> Optional[str]:
    """Returns user_id if token is valid and not expired, else None."""
    conn = _get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT user_id, expires_at FROM auth.sessions
            WHERE refresh_token_hash = %s AND revoked = FALSE
            """,
            (_hash_code(raw_token),),
        )
        row = cur.fetchone()
        if not row:
            return None
        if datetime.utcnow() > row["expires_at"].replace(tzinfo=None):
            return None
        cur.execute(
            "UPDATE auth.sessions SET last_used_at = NOW() WHERE refresh_token_hash = %s",
            (_hash_code(raw_token),),
        )
        conn.commit()
        return str(row["user_id"])
    finally:
        conn.close()


def revoke_session(raw_token: str):
    conn = _get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            "UPDATE auth.sessions SET revoked = TRUE WHERE refresh_token_hash = %s",
            (_hash_code(raw_token),),
        )
        conn.commit()
    finally:
        conn.close()


# ─────────────────────────────────────────
# AUDIT LOG (PostgreSQL — replaces SQLite)
# ─────────────────────────────────────────
def log_audit_pg(user_id: str, tier: str, action: str, details: str, status: str):
    """Write audit entry to PostgreSQL. Non-fatal on failure."""
    try:
        conn = _get_conn()
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO auth.audit_logs (user_id, tier, action, details, status)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (user_id, tier, action, details, status),
        )
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"[auth_db] Audit log error: {e}")


def get_audit_logs_pg(limit: int = 100):
    conn = _get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT id, timestamp, user_id, tier, action, details, status
            FROM auth.audit_logs
            ORDER BY timestamp DESC
            LIMIT %s
            """,
            (limit,),
        )
        rows = cur.fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()
