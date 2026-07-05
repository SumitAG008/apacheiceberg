# test_regression.py
"""
Automated regression test suite for LakeMind / Meldra AI API.
Uses pytest and FastAPI TestClient.

Run from backend directory with:
    pytest -v tests/test_regression.py

Test ordering matters: registration -> verify -> login -> authenticated routes.
Tests share state through module-scoped fixtures.
"""

import sys
import os
import uuid
import pytest
from fastapi.testclient import TestClient

# Add parent directory to path so api.main can be imported
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from api.main import app
import mfa_service
from auth_db import _get_conn

client = TestClient(app)

# ── Shared OTP capture dict ───────────────────────────────────────────────────
# Persists across all tests (cleared only in teardown fixture).
# We do NOT use autouse=True so the dict survives across test functions.
captured_otps: dict = {}

# ── Mock OTP delivery – module-scoped so it wraps ALL tests ──────────────────
@pytest.fixture(scope="module", autouse=True)
def mock_otp_delivery(monkeypatch_module):
    """
    Intercept send_email_otp for the entire module so no real emails are sent
    and every generated OTP code is captured for use in tests.
    """
    def mock_send(to_email: str, code: str, purpose: str = "login"):
        # Always overwrite — each call is the freshest code for that email
        captured_otps[to_email] = {"code": code, "purpose": purpose}
        print(f"\n[MOCK EMAIL] Captured OTP for {to_email}: {code} (purpose={purpose})")
        return True

    # Must patch in api.main namespace (where it was imported via `from mfa_service import ...`)
    monkeypatch_module.setattr("api.main.send_email_otp", mock_send)
    yield


@pytest.fixture(scope="module")
def monkeypatch_module():
    """Module-scoped monkeypatch (pytest's built-in monkeypatch is function-scoped)."""
    from _pytest.monkeypatch import MonkeyPatch
    mp = MonkeyPatch()
    yield mp
    mp.undo()


# ── Test user credentials (shared across module) ─────────────────────────────
@pytest.fixture(scope="module")
def test_user_credentials():
    rand_id = uuid.uuid4().hex[:8]
    email = f"test_reg_{rand_id}@example.com"
    password = "Password123!"
    yield {"email": email, "password": password}

    # Teardown — delete test user from PostgreSQL
    try:
        conn = _get_conn()
        cur = conn.cursor()
        cur.execute("DELETE FROM auth.users WHERE email = %s", (email,))
        conn.commit()
        print(f"\n[TEARDOWN] Deleted test user: {email}")
        conn.close()
    except Exception as e:
        print(f"\n[TEARDOWN] Cleanup error: {e}")


# ── Helper: do a full login + MFA verify cycle, return access_token ───────────
def _full_login(email: str, password: str) -> str:
    """Performs login + MFA verification and returns a valid access_token."""
    login_res = client.post("/auth/login", json={"email": email, "password": password})
    assert login_res.status_code == 200, f"Login failed: {login_res.text}"
    temp_token = login_res.json()["temp_token"]

    otp_entry = captured_otps.get(email)
    assert otp_entry is not None, "OTP was not captured — mock may not be active"
    otp_code = otp_entry["code"]

    verify_res = client.post("/auth/verify-mfa", json={"temp_token": temp_token, "code": otp_code})
    assert verify_res.status_code == 200, f"verify-mfa failed: {verify_res.text}"
    return verify_res.json()["access_token"]


# ═════════════════════════════════════════════════════════════════════════════
# TEST CASES
# ═════════════════════════════════════════════════════════════════════════════

class TestHealthCheck:
    def test_health_endpoint_returns_ok(self):
        """Health endpoint should return 200 with {status: ok}."""
        res = client.get("/health")
        assert res.status_code == 200
        assert res.json() == {"status": "ok"}


class TestAuthRegistration:
    def test_register_new_user(self, test_user_credentials):
        """
        POST /auth/register — should create user, send OTP, return temp_token.
        The OTP purpose at this stage is 'register'.
        """
        email = test_user_credentials["email"]
        password = test_user_credentials["password"]

        res = client.post("/auth/register", json={
            "email": email,
            "password": password,
            "mfa_method": "email"
        })
        assert res.status_code == 200, f"Registration failed: {res.text}"
        data = res.json()
        assert "temp_token" in data, "Response must contain temp_token"

        # OTP must have been captured by our mock
        assert email in captured_otps, "OTP was not captured — mock may not be active"
        assert captured_otps[email]["purpose"] == "register"

        # Store temp_token on the credentials dict for the next test
        test_user_credentials["reg_temp_token"] = data["temp_token"]

    def test_register_duplicate_email_rejected(self, test_user_credentials):
        """Registering the same email twice must return 400."""
        email = test_user_credentials["email"]
        password = test_user_credentials["password"]

        res = client.post("/auth/register", json={
            "email": email,
            "password": password,
            "mfa_method": "email"
        })
        assert res.status_code == 400, "Duplicate registration should be rejected with 400"


class TestAuthVerifyRegistration:
    def test_verify_registration_otp(self, test_user_credentials):
        """
        POST /auth/verify-mfa with purpose='register' OTP.
        This completes account activation and sets is_verified=True.
        Without this step, subsequent /auth/login will look for purpose='register'
        OTP in the MFA table (because is_verified is still False), causing 401.
        """
        email = test_user_credentials["email"]

        # After test_register_duplicate_email_rejected ran, the mock re-captured a fresh
        # 'register' OTP. Use the temp_token from the FIRST registration.
        temp_token = test_user_credentials.get("reg_temp_token")
        assert temp_token, "reg_temp_token not set — run registration test first"

        otp_entry = captured_otps.get(email)
        assert otp_entry is not None, "No OTP captured for this email"

        res = client.post("/auth/verify-mfa", json={
            "temp_token": temp_token,
            "code": otp_entry["code"]
        })
        assert res.status_code == 200, f"Registration OTP verification failed: {res.text}"
        data = res.json()
        assert "access_token" in data
        assert "refresh_token" in data
        assert data["token_type"] == "bearer"

        # Store access token for use in subsequent tests
        test_user_credentials["access_token"] = data["access_token"]


class TestAuthLogin:
    def test_login_with_valid_credentials(self, test_user_credentials):
        """
        POST /auth/login — must return temp_token and trigger OTP (purpose='login').
        User must already be verified (test_verify_registration_otp must have run first).
        """
        email = test_user_credentials["email"]
        password = test_user_credentials["password"]

        res = client.post("/auth/login", json={"email": email, "password": password})
        assert res.status_code == 200, f"Login failed: {res.text}"
        data = res.json()
        assert "temp_token" in data
        assert data.get("mfa_required") is True

        # OTP should be captured with purpose='login'
        assert email in captured_otps
        assert captured_otps[email]["purpose"] == "login"

    def test_login_with_wrong_password(self, test_user_credentials):
        """Wrong password must return 401."""
        email = test_user_credentials["email"]
        res = client.post("/auth/login", json={"email": email, "password": "WrongPass999!"})
        assert res.status_code == 401

    def test_verify_login_otp(self, test_user_credentials):
        """
        POST /auth/verify-mfa with purpose='login' OTP.
        Should return full JWT token pair.
        """
        email = test_user_credentials["email"]
        password = test_user_credentials["password"]

        # Fresh login to get a fresh temp_token + fresh OTP
        login_res = client.post("/auth/login", json={"email": email, "password": password})
        assert login_res.status_code == 200
        temp_token = login_res.json()["temp_token"]

        otp_entry = captured_otps.get(email)
        assert otp_entry is not None
        otp_code = otp_entry["code"]

        verify_res = client.post("/auth/verify-mfa", json={
            "temp_token": temp_token,
            "code": otp_code
        })
        assert verify_res.status_code == 200, f"Login MFA verify failed: {verify_res.text}"
        data = verify_res.json()
        assert "access_token" in data
        assert "refresh_token" in data

        # Store fresh access token
        test_user_credentials["access_token"] = data["access_token"]


class TestProtectedRoutes:
    def test_unauthenticated_request_blocked(self):
        """Protected routes must reject requests with no token."""
        res = client.get("/v1/config/aws")
        assert res.status_code == 401

    def test_get_aws_config_authenticated(self, test_user_credentials):
        """GET /v1/config/aws must return config for authenticated user."""
        email = test_user_credentials["email"]
        password = test_user_credentials["password"]
        access_token = _full_login(email, password)

        headers = {"Authorization": f"Bearer {access_token}"}
        res = client.get("/v1/config/aws", headers=headers)
        assert res.status_code == 200, f"Fetching config failed: {res.text}"
        assert "s3_warehouse_uri" in res.json()

    def test_audit_logs_retrieval(self, test_user_credentials):
        """GET /v1/audit must return a list of audit events for authenticated user."""
        email = test_user_credentials["email"]
        password = test_user_credentials["password"]
        access_token = _full_login(email, password)

        headers = {"Authorization": f"Bearer {access_token}"}
        res = client.get("/v1/audit", headers=headers)
        assert res.status_code == 200, f"Audit log fetch failed: {res.text}"
        assert isinstance(res.json(), list)

    def test_graph_stats_authenticated(self, test_user_credentials):
        """GET /v1/graph/stats must return graph statistics."""
        email = test_user_credentials["email"]
        password = test_user_credentials["password"]
        access_token = _full_login(email, password)

        headers = {"Authorization": f"Bearer {access_token}"}
        res = client.get("/v1/graph/stats", headers=headers)
        # Acceptable even if graph db not fully configured
        assert res.status_code in (200, 503), f"Unexpected status: {res.status_code}"

    def test_auth_me_returns_user_profile(self, test_user_credentials):
        """GET /auth/me must return the current user's profile."""
        email = test_user_credentials["email"]
        password = test_user_credentials["password"]
        access_token = _full_login(email, password)

        headers = {"Authorization": f"Bearer {access_token}"}
        res = client.get("/auth/me", headers=headers)
        assert res.status_code == 200, f"/auth/me failed: {res.text}"
        data = res.json()
        assert data["email"] == email


class TestInvalidOTP:
    def test_wrong_otp_rejected(self, test_user_credentials):
        """Submitting a wrong OTP to verify-mfa must return 401."""
        email = test_user_credentials["email"]
        password = test_user_credentials["password"]

        login_res = client.post("/auth/login", json={"email": email, "password": password})
        assert login_res.status_code == 200
        temp_token = login_res.json()["temp_token"]

        res = client.post("/auth/verify-mfa", json={
            "temp_token": temp_token,
            "code": "000000"  # Definitely wrong
        })
        assert res.status_code == 401
