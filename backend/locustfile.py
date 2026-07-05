# locustfile.py
"""
Meldra AI / LakeMind API — Load & Performance Test Suite
=========================================================
Uses Locust to simulate concurrent users hitting all major API endpoints.

Usage
-----
# Interactive Web UI (recommended for first run):
    locust -f backend/locustfile.py --host https://api.meldra.ai

# Headless CI/CD run (100 users, ramp 10/s, run 60s):
    locust -f backend/locustfile.py --host https://api.meldra.ai \\
           --users 100 --spawn-rate 10 --run-time 60s --headless

# Against local dev server:
    locust -f backend/locustfile.py --host http://localhost:8000

IMPORTANT
---------
Load test users are created with email prefix "load_test_*".
The backend has an explicit OTP bypass for these users (code="123456"),
so no real emails are sent during load testing.
"""

import uuid
import json
import random
import io
import csv
from locust import HttpUser, task, between, tag, events


# ── Helper: generate a small in-memory CSV payload ───────────────────────────
def _make_csv_payload(rows: int = 50) -> bytes:
    """Produce a tiny CSV file as bytes for /v1/upload-csv load tests."""
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["id", "ts", "customer_id", "amount", "status", "category"])
    categories = ["Electronics", "Apparel", "Home", "Food", "Sports"]
    statuses = ["completed", "pending", "refunded"]
    for i in range(rows):
        writer.writerow([
            i + 1,
            f"2024-{random.randint(1,12):02d}-{random.randint(1,28):02d}T{random.randint(0,23):02d}:00:00Z",
            random.randint(1000, 9999),
            round(random.uniform(5.0, 500.0), 2),
            random.choice(statuses),
            random.choice(categories),
        ])
    return buf.getvalue().encode("utf-8")


# ══════════════════════════════════════════════════════════════════════════════
# USER: Unauthenticated Read-Only (health checks, public paths)
# ══════════════════════════════════════════════════════════════════════════════
class PublicUser(HttpUser):
    """
    Simulates anonymous / unauthenticated traffic.
    Weight=1 → spawned less frequently than authenticated users.
    """
    weight = 1
    wait_time = between(0.5, 2)

    @tag("health", "smoke")
    @task(5)
    def health_check(self):
        """GET /health — should always be fast & 200."""
        self.client.get("/health", name="/health")

    @tag("auth", "negative")
    @task(2)
    def unauthenticated_config_blocked(self):
        """GET /v1/config/aws without token — expect 401."""
        with self.client.get(
            "/v1/config/aws",
            name="/v1/config/aws [unauth]",
            catch_response=True,
        ) as res:
            if res.status_code == 401:
                res.success()
            else:
                res.failure(f"Expected 401 but got {res.status_code}")

    @tag("auth", "negative")
    @task(1)
    def login_wrong_password(self):
        """POST /auth/login with bad credentials — expect 401."""
        with self.client.post(
            "/auth/login",
            json={"email": "nobody@example.com", "password": "wrongpass"},
            name="/auth/login [bad creds]",
            catch_response=True,
        ) as res:
            if res.status_code == 401:
                res.success()
            else:
                res.failure(f"Expected 401 but got {res.status_code}")


# ══════════════════════════════════════════════════════════════════════════════
# USER: Authenticated Heavy — register → verify → login → all endpoints
# ══════════════════════════════════════════════════════════════════════════════
class AuthenticatedUser(HttpUser):
    """
    Simulates a logged-in data engineer using the LakeMind platform.
    Weight=3 → spawned 3× more than PublicUser.
    """
    weight = 3
    wait_time = between(1, 4)

    token: str | None = None
    user_email: str = ""
    password: str = "Password123!"

    def on_start(self):
        """
        Perform full registration + OTP verification (using load_test bypass).
        Called once per simulated user at spawn time.
        """
        self.user_email = f"load_test_{uuid.uuid4().hex[:8]}@example.com"

        # ── Step 1: Register ──────────────────────────────────────────────────
        with self.client.post(
            "/auth/register",
            json={"email": self.user_email, "password": self.password, "mfa_method": "email"},
            name="/auth/register [setup]",
            catch_response=True,
        ) as reg_res:
            if reg_res.status_code != 200:
                reg_res.failure(f"Registration failed: {reg_res.text[:200]}")
                return
            temp_token = reg_res.json().get("temp_token")
            reg_res.success()

        # ── Step 2: Verify registration OTP (load_test bypass code=123456) ───
        with self.client.post(
            "/auth/verify-mfa",
            json={"temp_token": temp_token, "code": "123456"},
            name="/auth/verify-mfa [setup]",
            catch_response=True,
        ) as ver_res:
            if ver_res.status_code == 200:
                self.token = ver_res.json().get("access_token")
                ver_res.success()
            else:
                ver_res.failure(f"Verify-MFA failed: {ver_res.text[:200]}")

    def _headers(self) -> dict:
        if self.token:
            return {"Authorization": f"Bearer {self.token}"}
        return {}

    def _re_login(self):
        """Silently re-authenticate if token has expired."""
        login_res = self.client.post(
            "/auth/login",
            json={"email": self.user_email, "password": self.password},
            name="/auth/login [re-auth]",
        )
        if login_res.status_code == 200:
            temp_token = login_res.json().get("temp_token")
            ver_res = self.client.post(
                "/auth/verify-mfa",
                json={"temp_token": temp_token, "code": "123456"},
                name="/auth/verify-mfa [re-auth]",
            )
            if ver_res.status_code == 200:
                self.token = ver_res.json().get("access_token")

    # ── Tasks ─────────────────────────────────────────────────────────────────

    @tag("health")
    @task(3)
    def health_check(self):
        """Lightweight health probe — high frequency."""
        self.client.get("/health", name="/health")

    @tag("config", "read")
    @task(4)
    def get_aws_config(self):
        """GET /v1/config/aws — most common authenticated read."""
        with self.client.get(
            "/v1/config/aws",
            headers=self._headers(),
            name="/v1/config/aws",
            catch_response=True,
        ) as res:
            if res.status_code == 401:
                self._re_login()
                res.failure("Token expired — re-authenticated")
            elif res.status_code not in (200, 404):
                res.failure(f"Unexpected: {res.status_code}")

    @tag("audit", "read")
    @task(2)
    def get_audit_logs(self):
        """GET /v1/audit — audit trail fetch."""
        with self.client.get(
            "/v1/audit",
            headers=self._headers(),
            name="/v1/audit",
            catch_response=True,
        ) as res:
            if res.status_code == 401:
                self._re_login()
                res.failure("Token expired — re-authenticated")
            elif res.status_code not in (200,):
                res.failure(f"Audit logs returned {res.status_code}")

    @tag("graph", "read")
    @task(2)
    def get_graph_stats(self):
        """GET /v1/graph/stats — graph database stats."""
        with self.client.get(
            "/v1/graph/stats",
            headers=self._headers(),
            name="/v1/graph/stats",
            catch_response=True,
        ) as res:
            # 503 is acceptable when graph DB is not reachable
            if res.status_code not in (200, 503):
                res.failure(f"Graph stats returned {res.status_code}")

    @tag("user", "read")
    @task(1)
    def get_profile(self):
        """GET /auth/me — user profile lookup."""
        with self.client.get(
            "/auth/me",
            headers=self._headers(),
            name="/auth/me",
            catch_response=True,
        ) as res:
            if res.status_code == 401:
                self._re_login()
                res.failure("Token expired — re-authenticated")

    @tag("chat", "ai")
    @task(2)
    def send_chat_message(self):
        """POST /v1/chat — AI query (main revenue feature)."""
        questions = [
            "How many rows are in the sap_bseg table?",
            "Show me the top 5 customers by revenue",
            "What is the total transaction volume this month?",
            "List all tables in the default namespace",
            "What is a data lakehouse?",
        ]
        payload = {"message": random.choice(questions), "session_id": str(uuid.uuid4())}
        with self.client.post(
            "/v1/chat",
            json=payload,
            headers=self._headers(),
            name="/v1/chat",
            catch_response=True,
        ) as res:
            if res.status_code == 401:
                self._re_login()
                res.failure("Token expired — re-authenticated")
            elif res.status_code not in (200, 500, 503):
                res.failure(f"Chat returned {res.status_code}")

    @tag("ingest", "write", "heavy")
    @task(1)
    def upload_csv(self):
        """
        POST /v1/upload-csv — upload a small synthetic CSV.
        Lower task weight (1) as it is a heavy write operation.
        """
        csv_bytes = _make_csv_payload(rows=random.randint(20, 100))
        files = {"file": ("load_test_data.csv", csv_bytes, "text/csv")}
        with self.client.post(
            "/v1/upload-csv",
            files=files,
            headers=self._headers(),
            name="/v1/upload-csv",
            catch_response=True,
        ) as res:
            if res.status_code == 401:
                self._re_login()
                res.failure("Token expired — re-authenticated")
            elif res.status_code not in (200, 202, 400, 422):
                res.failure(f"Upload returned {res.status_code}")

    @tag("graph", "write")
    @task(1)
    def run_cypher_query(self):
        """POST /v1/graph/cypher — graph query execution."""
        payload = {"query": "MATCH (n) RETURN count(n) AS total LIMIT 1"}
        with self.client.post(
            "/v1/graph/cypher",
            json=payload,
            headers=self._headers(),
            name="/v1/graph/cypher",
            catch_response=True,
        ) as res:
            if res.status_code not in (200, 400, 503):
                res.failure(f"Cypher returned {res.status_code}")


# ══════════════════════════════════════════════════════════════════════════════
# USER: CSV Ingest Stress — simulates a bulk data pipeline hammering the API
# ══════════════════════════════════════════════════════════════════════════════
class IngestStressUser(HttpUser):
    """
    Dedicated bulk ingest user. Uploads large CSVs repeatedly.
    Use with --users 10 --spawn-rate 2 to avoid overwhelming S3.
    Weight=1 → spawned least frequently.
    """
    weight = 1
    wait_time = between(2, 6)

    token: str | None = None
    user_email: str = ""
    password: str = "Password123!"

    def on_start(self):
        self.user_email = f"load_test_{uuid.uuid4().hex[:8]}@example.com"
        reg_res = self.client.post(
            "/auth/register",
            json={"email": self.user_email, "password": self.password, "mfa_method": "email"},
            name="/auth/register [ingest-setup]",
        )
        if reg_res.status_code == 200:
            temp_token = reg_res.json().get("temp_token")
            ver_res = self.client.post(
                "/auth/verify-mfa",
                json={"temp_token": temp_token, "code": "123456"},
                name="/auth/verify-mfa [ingest-setup]",
            )
            if ver_res.status_code == 200:
                self.token = ver_res.json().get("access_token")

    @tag("ingest", "stress")
    @task(1)
    def bulk_upload(self):
        """Upload a large CSV (500-2000 rows) to stress the ingest pipeline."""
        csv_bytes = _make_csv_payload(rows=random.randint(500, 2000))
        files = {"file": (f"bulk_{uuid.uuid4().hex[:6]}.csv", csv_bytes, "text/csv")}
        headers = {"Authorization": f"Bearer {self.token}"} if self.token else {}
        with self.client.post(
            "/v1/upload-csv",
            files=files,
            headers=headers,
            name="/v1/upload-csv [bulk]",
            catch_response=True,
        ) as res:
            if res.status_code not in (200, 202, 400, 422):
                res.failure(f"Bulk upload returned {res.status_code}: {res.text[:100]}")
