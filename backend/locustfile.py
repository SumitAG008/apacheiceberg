# locustfile.py
# Run with: locust -f locustfile.py
# Then open http://localhost:8089 in your browser to configure load test.

import time
import uuid
from locust import HttpUser, task, between

class MeldraApiUser(HttpUser):
    # Simulate a user thinking for 1 to 3 seconds between tasks
    wait_time = between(1, 3)
    token = None
    user_email = None

    def on_start(self):
        """Called when a simulated user starts. Performs login/auth flow."""
        self.user_email = f"load_test_{uuid.uuid4().hex[:6]}@example.com"
        self.password = "Password123"
        
        # 1. Register User
        reg_payload = {
            "email": self.user_email,
            "password": self.password,
            "mfa_method": "email"
        }
        res = self.client.post("/auth/register", json=reg_payload)
        
        if res.status_code == 200:
            temp_token = res.json().get("temp_token")
            # In a real test, OTP is sent via email. For load testing, we simulate 
            # by fetching the token or bypassing/using a mock code in test mode.
            # Here we simulate OTP verification
            verify_payload = {
                "temp_token": temp_token,
                "code": "123456" # Assumes test environment mock code
            }
            # Note: We bypass strict checks for test emails in backend if needed.
            # If verify-mfa fails due to invalid OTP in production databases, 
            # we run unauthenticated read/health tests.
            verify_res = self.client.post("/auth/verify-mfa", json=verify_payload)
            if verify_res.status_code == 200:
                self.token = verify_res.json().get("access_token")

    @task(3)
    def test_health(self):
        """Standard unauthenticated health check endpoint."""
        self.client.get("/health")

    @task(2)
    def test_get_config(self):
        """Retrieve AWS configurations (authenticated)."""
        headers = {}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        self.client.get("/v1/config/aws", headers=headers)

    @task(1)
    def test_mcp_execution(self):
        """Simulate load on the MCP Tool Broker endpoint."""
        headers = {}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
            
        payload = {
            "server_name": "Iceberg Catalog MCP Server",
            "tool_name": "query_iceberg_data",
            "arguments": {
                "namespace": "default",
                "table_name": "sap_bseg",
                "sql_query": "SELECT * FROM iceberg_table LIMIT 5"
            }
        }
        self.client.post("/v1/mcp/execute", json=payload, headers=headers)
