# Copyright (c) 2026 Meldra AI Ltd. All rights reserved.
"""
tests/test_etp_endpoints.py

Validates live FastAPI ETP REST API endpoints (/v1/etp/ingest, /v1/etp/checkpoint, 
/v1/etp/query/verify, /v1/etp/honeypot/stix) to guarantee zero 503 initialization failures.
"""

from __future__ import annotations

import sys
import os
import json
import time
from pathlib import Path

root_dir = Path(__file__).resolve().parent.parent.parent
backend_dir = Path(__file__).resolve().parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

os.environ.setdefault("ENVIRONMENT", "development")

import pytest
from fastapi.testclient import TestClient

from backend.api.main import app, _create_access_token
from backend.etp.meter import SmartMeterSimulator
from backend.etp.route_mutator import RouteMutator


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def auth_headers():
    token = _create_access_token({
        "sub": "user_ci_test_123",
        "email": "test@meldra.ai",
        "tier": "enterprise",
        "role": "Admin"
    })
    return {"Authorization": f"Bearer {token}"}


def test_etp_gateway_initialization_not_503(client, auth_headers):
    """Verifies ETP gateway engine is properly initialized and does not return 503."""
    response = client.get("/v1/etp/honeypot/stix", headers=auth_headers)
    assert response.status_code != 503, f"ETP gateway returned 503: {response.json()}"
    assert response.status_code == 200
    data = response.json()
    assert data.get("type") == "bundle"


def test_etp_checkpoint_endpoint(client, auth_headers):
    """Verifies POST /v1/etp/checkpoint builds a Merkle checkpoint with omission detection."""
    reading = {
        "mpan": "MPAN-TEST-001",
        "reading_ts": "2026-09-20T23:00:00.000Z",
        "reading_kwh": 12.345,
        "etp_block_hash": "00" * 32,
        "etp_nonce": 100,
        "etp_verify_status": "VERIFIED"
    }
    payload = {
        "mpan": "MPAN-TEST-001",
        "day": "2026-09-20",
        "readings": [reading],
        "expected_daily_readings": 48
    }
    response = client.post("/v1/etp/checkpoint", json=payload, headers=auth_headers)
    assert response.status_code == 200
    cp = response.json()
    assert cp["mpan"] == "MPAN-TEST-001"
    assert cp["eod_gap"] == 47  # 1 reading out of 48 expected -> eod_gap = 47
    assert cp["status"] == "ANCHORED_WITH_GAPS"


def test_etp_query_verify_endpoint(client, auth_headers):
    """Verifies POST /v1/etp/query/verify emits a VerificationAwareQueryObject."""
    reading = {
        "mpan": "MPAN-TEST-002",
        "reading_ts": "2026-09-20T23:00:00.000Z",
        "reading_kwh": 0.412,
        "etp_block_hash": "00" * 32,
        "etp_nonce": 100,
        "etp_verify_status": "VERIFIED"
    }
    payload = {
        "query_id": "q_test_123",
        "sql_string": "SELECT mpan, reading_kwh FROM telemetry",
        "snapshot_id": 999888777,
        "result_set": [{"mpan": "MPAN-TEST-002", "reading_kwh": 0.412}],
        "contributing_readings": [reading]
    }
    response = client.post("/v1/etp/query/verify", json=payload, headers=auth_headers)
    assert response.status_code == 200
    query_obj = response.json()
    assert query_obj["query_id"] == "q_test_123"
    assert "verification_proof" in query_obj
    assert query_obj["verification_proof"]["total_rows_scanned"] == 1


def test_etp_ingest_endpoint(client, auth_headers):
    """Verifies POST /v1/etp/ingest exercises full security pipeline (route validation, schema check, signature verification, state commit)."""
    from backend.api.main import etp_gateway, etp_route_mutator
    assert etp_gateway is not None, "ETP Gateway engine not initialized"

    meter = SmartMeterSimulator(mpan="MPAN-INGEST-TEST-001")
    etp_gateway.register_meter_public_key(meter.mpan, meter.public_key)

    now_epoch_s = int(time.time())
    route = etp_route_mutator.active_routes(now_epoch_s)["current"]

    block = meter.generate_block(reading_kwh=15.678)
    block_dict = block.to_dict()
    block_dict["route"] = route

    response = client.post("/v1/etp/ingest", json=block_dict, headers=auth_headers)
    assert response.status_code == 200, f"Expected 200 OK, got {response.status_code}: {response.json()}"
    resp_data = response.json()
    assert resp_data.get("status") == "accepted"
    assert resp_data.get("verify_status") == "VERIFIED"
    assert resp_data.get("block_hash") == block.block_hash


def test_etp_sample_proof_pack_verifies(client):
    """Verifies GET /v1/etp/sample-proof-pack generates a proof pack that passes /v1/etp/proof-pack/verify."""
    resp_sample = client.get("/v1/etp/sample-proof-pack")
    assert resp_sample.status_code == 200
    pack = resp_sample.json()
    assert "merkle_root" in pack
    assert "readings" in pack
    assert len(pack["readings"]) == 42

    resp_verify = client.post("/v1/etp/proof-pack/verify", json={"proof_pack": pack})
    assert resp_verify.status_code == 200
    data = resp_verify.json()
    assert data["verified"] is True
    assert data["status"] == "ANCHORED_WITH_GAPS"
    assert data["sequence_gap_count"] == 6


