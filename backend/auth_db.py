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
from datetime import datetime, timedelta, timezone
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
    db_url = os.environ.get("DATABASE_URL")
    if db_url:
        # Fallback to connection string if DATABASE_URL is present
        return psycopg2.connect(db_url, cursor_factory=psycopg2.extras.RealDictCursor)
    return psycopg2.connect(
        host=os.environ.get("GRAPH_DB_HOST") or "localhost",
        port=int(os.environ.get("GRAPH_DB_PORT") or 5432),
        user=os.environ.get("GRAPH_DB_USER") or "postgres",
        password=os.environ.get("GRAPH_DB_PASSWORD") or "",
        dbname=os.environ.get("GRAPH_DB_NAME") or "graphdb",
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
                subscription_status TEXT NOT NULL DEFAULT 'active', -- 'active' | 'expired' | 'canceled'
                user_role       TEXT NOT NULL DEFAULT 'Business Analyst' -- see roles.ALL_ROLES: Admin | Data Engineer | Data Architect | Business Analyst | Consultant | CIO | COO | Viewer
            );
        """)

        # Run database migrations for existing tables in Neon automatically
        cur.execute("ALTER TABLE auth.users ADD COLUMN IF NOT EXISTS tier TEXT NOT NULL DEFAULT 'trial';")
        cur.execute("ALTER TABLE auth.users ADD COLUMN IF NOT EXISTS expires_at TIMESTAMPTZ;")
        cur.execute("ALTER TABLE auth.users ADD COLUMN IF NOT EXISTS reg_ip TEXT;")
        cur.execute("ALTER TABLE auth.users ADD COLUMN IF NOT EXISTS reg_country TEXT;")
        cur.execute("ALTER TABLE auth.users ADD COLUMN IF NOT EXISTS subscription_status TEXT NOT NULL DEFAULT 'active';")
        cur.execute("ALTER TABLE auth.users ADD COLUMN IF NOT EXISTS user_role TEXT NOT NULL DEFAULT 'Business Analyst';")
        cur.execute("ALTER TABLE auth.users ADD COLUMN IF NOT EXISTS sso_provider TEXT;")
        # Approver is a designation independent of role/persona (an Admin
        # flags specific trusted users) -- see promotions.py. Deliberately
        # not role-derived: "who can approve" is a separate question from
        # "what can this role do day to day."
        cur.execute("ALTER TABLE auth.users ADD COLUMN IF NOT EXISTS is_approver BOOLEAN NOT NULL DEFAULT FALSE;")

        cur.execute("""
            CREATE TABLE IF NOT EXISTS auth.promotions (
                id              BIGSERIAL PRIMARY KEY,
                tenant_id       TEXT NOT NULL,
                pipeline_name   TEXT NOT NULL,
                environment     TEXT NOT NULL,           -- 'staging' | 'production'
                version_ref     TEXT NOT NULL,           -- git sha or version label being promoted
                notes           TEXT,
                status          TEXT NOT NULL DEFAULT 'pending',  -- 'pending' | 'approved' | 'rejected' | 'deployed'
                requested_by    UUID NOT NULL REFERENCES auth.users(id),
                requested_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                decided_by      UUID REFERENCES auth.users(id),
                decided_at      TIMESTAMPTZ,
                decision_notes  TEXT
            );
        """)
        cur.execute("CREATE INDEX IF NOT EXISTS idx_promotions_tenant ON auth.promotions(tenant_id, requested_at DESC);")

        cur.execute("""
            CREATE TABLE IF NOT EXISTS auth.rbac_policies (
                id              BIGSERIAL PRIMARY KEY,
                role            TEXT NOT NULL,
                namespace       TEXT NOT NULL,
                table_name      TEXT NOT NULL,
                column_name     TEXT NOT NULL,
                -- 'mask' | 'deny' for a real column, or 'deny' with
                -- column_name = '__TABLE__' to deny the entire table/namespace
                -- to this role (namespace-level when table_name = '*').
                action          TEXT NOT NULL DEFAULT 'mask',
                masking_pattern TEXT NOT NULL DEFAULT '***'
            );
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS auth.rbac_row_filters (
                id                BIGSERIAL PRIMARY KEY,
                role              TEXT NOT NULL,
                namespace         TEXT NOT NULL,
                table_name        TEXT NOT NULL,  -- or '*' for every table in the namespace
                filter_expression TEXT NOT NULL,  -- pandas .query() expression, e.g. "region == 'EMEA'"
                description       TEXT,
                created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
        """)

        # Add default demo policies for Business Analyst role if table is empty
        cur.execute("SELECT count(*) FROM auth.rbac_policies;")
        if cur.fetchone()["count"] == 0:
            default_policies = [
                ('Business Analyst', 'default', 'sap_hr_data', 'performance_rating', 'mask', '***'),
                ('Business Analyst', 'default', 'sap_hr_data', 'projects_count', 'mask', '***'),
                ('Business Analyst', 'default', 'vendors_10k_50col', 'bank_account', 'mask', 'BANK-***'),
                ('Business Analyst', 'default', 'vendors_10k_50col', 'tax_id', 'mask', 'XX-***'),
                ('Business Analyst', 'default', 'vendors_10k_50col', 'routing_number', 'mask', 'ROUT-***'),
                ('Business Analyst', 'default', 'vendors_10k_50col', 'annual_spend', 'mask', '###.##'),
                # Consultant is deny-by-default on every namespace (see
                # rbac_utils.check_table_access) — an Admin grants access to
                # a specific engagement's namespace with an explicit 'allow'
                # policy row rather than this account having standing access
                # to anything up front.
                ('Consultant', '*', '*', '__TABLE__', 'deny', '***'),
            ]
            for p in default_policies:
                cur.execute("""
                    INSERT INTO auth.rbac_policies (role, namespace, table_name, column_name, action, masking_pattern)
                    VALUES (%s, %s, %s, %s, %s, %s);
                """, p)

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
        cur.execute("CREATE INDEX IF NOT EXISTS idx_rbac_role ON auth.rbac_policies(role);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_rbac_row_filters_role ON auth.rbac_row_filters(role);")

        conn.commit()
        print("[auth_db] Auth schema initialised successfully with geo, membership, expiration, and RBAC parameters.")
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
    reg_country: Optional[str] = None,
    user_role: str = "Business Analyst"
) -> Dict[str, Any]:
    conn = _get_conn()
    try:
        cur = conn.cursor()
        pwd_hash = hash_password(password)
        
        # Calculate 30-day expiration for trial memberships
        expires_at = None
        if tier == "trial":
            expires_at = datetime.now(timezone.utc) + timedelta(days=30)
            
        cur.execute(
            """
            INSERT INTO auth.users (email, password_hash, mfa_method, phone, tier, expires_at, reg_ip, reg_country, user_role)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id, email, mfa_method, phone, is_verified, created_at, tier, expires_at, reg_ip, reg_country, subscription_status, user_role
            """,
            (email.lower().strip(), pwd_hash, mfa_method, phone, tier, expires_at, reg_ip, reg_country, user_role),
        )
        user = dict(cur.fetchone())
        conn.commit()
        return user
    except psycopg2.errors.UniqueViolation:
        conn.rollback()
        raise ValueError(f"Email {email} is already registered.")
    finally:
        conn.close()


def get_or_create_sso_user(email: str, provider: str, user_role: str = "Business Analyst") -> Dict[str, Any]:
    """
    Looks up a user by email; if none exists, provisions one for SSO login.
    An SSO-provisioned account gets a random unusable password (the IdP is
    the actual authenticator — this account never logs in with a password
    directly) and is marked verified immediately, since the identity
    provider already verified the person before redirecting back here.
    """
    existing = get_user_by_email(email)
    if existing:
        return existing

    conn = _get_conn()
    try:
        cur = conn.cursor()
        unusable_password_hash = hash_password(secrets.token_urlsafe(32))
        cur.execute(
            """
            INSERT INTO auth.users (email, password_hash, mfa_method, is_verified, tier, user_role, sso_provider)
            VALUES (%s, %s, 'email', TRUE, 'trial', %s, %s)
            RETURNING id, email, mfa_method, phone, is_verified, created_at, tier, expires_at, reg_ip, reg_country, subscription_status, user_role, sso_provider
            """,
            (email.lower().strip(), unusable_password_hash, user_role, provider),
        )
        user = dict(cur.fetchone())
        conn.commit()
        return user
    except psycopg2.errors.UniqueViolation:
        conn.rollback()
        # Lost a race with a concurrent SSO login for the same new email.
        return get_user_by_email(email)
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


def update_password(user_id: str, new_password: str):
    """Set a new bcrypt-hashed password for the given user."""
    conn = _get_conn()
    try:
        cur = conn.cursor()
        pwd_hash = hash_password(new_password)
        cur.execute(
            "UPDATE auth.users SET password_hash = %s WHERE id = %s",
            (pwd_hash, user_id),
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
        expires_at = datetime.now(timezone.utc) + timedelta(minutes=MFA_OTP_EXPIRE_MINUTES)
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

        if datetime.now(timezone.utc) > row["expires_at"].replace(tzinfo=None):
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
        elapsed = datetime.now(timezone.utc) - row["created_at"].replace(tzinfo=None)
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
        expires_at = datetime.now(timezone.utc) + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
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
        if datetime.now(timezone.utc) > row["expires_at"].replace(tzinfo=None):
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


def set_user_approver(email: str, is_approver: bool):
    conn = _get_conn()
    try:
        cur = conn.cursor()
        cur.execute("UPDATE auth.users SET is_approver = %s WHERE email = %s;", (is_approver, email.lower().strip()))
        conn.commit()
    finally:
        conn.close()


def list_all_users(limit: int = 200) -> List[Dict[str, Any]]:
    """
    Every registered user with their current role/approver status — the
    directory an Admin needs to actually assign roles to real people
    instead of typing an email into a box and hoping it's right. Without
    this, /v1/rbac/user-role has no discoverable way to know who exists.
    """
    conn = _get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT id, email, user_role, is_approver, is_verified, is_active, created_at, last_login_at
            FROM auth.users
            ORDER BY created_at DESC
            LIMIT %s;
            """,
            (limit,),
        )
        return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


def list_approvers() -> List[Dict[str, Any]]:
    """Every user currently flagged as an approver — for the Admin UI that
    manages this designation."""
    conn = _get_conn()
    try:
        cur = conn.cursor()
        cur.execute("SELECT id, email, user_role FROM auth.users WHERE is_approver = TRUE ORDER BY email;")
        return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


def ensure_bootstrap_admin(user_id: str) -> Optional[str]:
    """If the whole platform has zero Admins, promote this logging-in user.

    Every new registration defaults to 'Business Analyst' (see auth.users'
    column default) and the Users & Roles page that assigns roles itself
    requires Admin — with no Admin ever created, nobody could ever reach
    it. Called on every successful login/MFA-verify; a no-op once any
    Admin exists. Returns the new role if a promotion happened, else None.
    """
    conn = _get_conn()
    try:
        cur = conn.cursor()
        cur.execute("SELECT 1 FROM auth.users WHERE user_role = 'Admin' LIMIT 1;")
        if cur.fetchone():
            return None
        cur.execute(
            "UPDATE auth.users SET user_role = 'Admin' WHERE id = %s RETURNING user_role;",
            (user_id,),
        )
        row = cur.fetchone()
        conn.commit()
        return row["user_role"] if row else None
    finally:
        conn.close()


# ─────────────────────────────────────────
# PROMOTIONS (real pipeline promotion workflow)
# ─────────────────────────────────────────
def create_promotion(
    tenant_id: str,
    pipeline_name: str,
    environment: str,
    version_ref: str,
    requested_by: str,
    notes: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Staging promotions don't need a second approver -- they go straight to
    'deployed'. Production promotions start 'pending' and require a
    decide_promotion() call from someone other than requested_by (enforced
    in api/main.py, not here -- this function just records the request).
    """
    conn = _get_conn()
    try:
        cur = conn.cursor()
        status = "deployed" if environment == "staging" else "pending"
        cur.execute(
            """
            INSERT INTO auth.promotions (tenant_id, pipeline_name, environment, version_ref, notes, status, requested_by)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            RETURNING id, tenant_id, pipeline_name, environment, version_ref, notes, status,
                      requested_by, requested_at, decided_by, decided_at, decision_notes;
            """,
            (tenant_id, pipeline_name, environment, version_ref, notes, status, requested_by),
        )
        row = dict(cur.fetchone())
        conn.commit()
        return row
    finally:
        conn.close()


def list_promotions(tenant_id: Optional[str], limit: int = 50) -> List[Dict[str, Any]]:
    """
    tenant_id=None returns promotions across every account — this platform
    has no organization/team concept (see tenancy.py: one tenant = one
    account), so a requester and their approver are never in the same
    tenant. Approver is deliberately a cross-cutting designation (see
    roles.py), so api/main.py passes tenant_id=None only when the caller
    is a designated Approver; everyone else is scoped to their own tenant.
    """
    conn = _get_conn()
    try:
        cur = conn.cursor()
        base_query = """
            SELECT p.id, p.tenant_id, p.pipeline_name, p.environment, p.version_ref, p.notes, p.status,
                   p.requested_by, ru.email AS requested_by_email, p.requested_at,
                   p.decided_by, du.email AS decided_by_email, p.decided_at, p.decision_notes
            FROM auth.promotions p
            JOIN auth.users ru ON ru.id = p.requested_by
            LEFT JOIN auth.users du ON du.id = p.decided_by
        """
        if tenant_id is None:
            cur.execute(base_query + " ORDER BY p.requested_at DESC LIMIT %s;", (limit,))
        else:
            cur.execute(base_query + " WHERE p.tenant_id = %s ORDER BY p.requested_at DESC LIMIT %s;", (tenant_id, limit))
        return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


def get_promotion(promotion_id: int) -> Optional[Dict[str, Any]]:
    conn = _get_conn()
    try:
        cur = conn.cursor()
        cur.execute("SELECT * FROM auth.promotions WHERE id = %s;", (promotion_id,))
        row = cur.fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def decide_promotion(promotion_id: int, decided_by: str, approve: bool, decision_notes: Optional[str] = None) -> Dict[str, Any]:
    """Records the approve/reject decision. Caller (api/main.py) is
    responsible for checking is_approver and the no-self-approval rule
    *before* calling this -- this function trusts its inputs."""
    conn = _get_conn()
    try:
        cur = conn.cursor()
        new_status = "deployed" if approve else "rejected"
        cur.execute(
            """
            UPDATE auth.promotions
            SET status = %s, decided_by = %s, decided_at = NOW(), decision_notes = %s
            WHERE id = %s
            RETURNING id, tenant_id, pipeline_name, environment, version_ref, notes, status,
                      requested_by, requested_at, decided_by, decided_at, decision_notes;
            """,
            (new_status, decided_by, decision_notes, promotion_id),
        )
        row = cur.fetchone()
        conn.commit()
        return dict(row) if row else None
    finally:
        conn.close()


def get_audit_logs_pg(limit: int = 100, user_id: Optional[str] = None):
    """
    Fetch audit log entries. If `user_id` is given, scoped to just that
    user's own actions (the tenant boundary — every account is its own
    tenant, so "your audit trail" means "your user_id's rows", not the
    platform's). Pass user_id=None only for genuinely platform-wide views
    (there currently are none exposed to non-Admin callers).
    """
    conn = _get_conn()
    try:
        cur = conn.cursor()
        if user_id is not None:
            cur.execute(
                """
                SELECT id, timestamp, user_id, tier, action, details, status
                FROM auth.audit_logs
                WHERE user_id = %s
                ORDER BY timestamp DESC
                LIMIT %s
                """,
                (user_id, limit),
            )
        else:
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
