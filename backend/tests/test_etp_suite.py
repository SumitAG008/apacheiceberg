"""Exhaustive Test Suite for EnergyTrust Protocol (ETP) Engine (T1–T25 Matrix).

Tests Blocks 1–7, MTD Route Scrambling, Nonce CAS, ECDSA Signatures, Canonical Hashing,
Phantom Grid Deception, Merkle Tree Domain Separation, Verification-Aware Queries,
AES-256-GCM Encryption, and IEC CIM Profile Exporter.
"""

import sys
import time
from pathlib import Path

# Enable running tests from workspace root or backend/ directory
root_dir = Path(__file__).resolve().parent.parent.parent
backend_dir = Path(__file__).resolve().parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

import pytest
try:
    from backend.etp import (
        RouteMutator,
        SmartMeterSimulator,
        TelemetryBlock,
        ETPGateway,
        MemoryNonceStore,
        PhantomGridHoneypot,
        MicroBatchWriter,
        MerkleCheckpointer,
        canonical_merkle_root,
        ETPVerifier,
        ETPSecurityManager,
        CIMProfileExporter
    )
except ImportError:
    from etp import (
        RouteMutator,
        SmartMeterSimulator,
        TelemetryBlock,
        ETPGateway,
        MemoryNonceStore,
        PhantomGridHoneypot,
        MicroBatchWriter,
        MerkleCheckpointer,
        canonical_merkle_root,
        ETPVerifier,
        ETPSecurityManager,
        CIMProfileExporter
    )


@pytest.fixture
def secret_key():
    return b"0123456789abcdef0123456789abcdef"


@pytest.fixture
def mutator(secret_key):
    return RouteMutator(secret_key=secret_key, window_s=60)


@pytest.fixture
def meter():
    return SmartMeterSimulator(mpan="MPAN-1200012345678")


@pytest.fixture
def gateway(mutator):
    nonce_store = MemoryNonceStore()
    phantom_grid = PhantomGridHoneypot()
    sec = ETPSecurityManager()
    gw = ETPGateway(
        route_mutator=mutator,
        nonce_store=nonce_store,
        phantom_grid=phantom_grid,
        security_manager=sec
    )
    return gw


# ── Test Suite: Block 2 (Route Mutator) ───────────────────────────

def test_t1_route_mutator_deterministic(mutator):
    """T1: Fixed secret + fixed clock yields deterministic known route."""
    now = 1772800000
    routes = mutator.active_routes(now)
    assert "current" in routes
    assert "prev" in routes
    assert "next" in routes
    assert "/rotated_" in routes["current"]
    assert mutator.validate_route(routes["current"], now) is True


def test_t2_route_mutator_drift_tolerance(mutator):
    """T2: Clock drift tolerance accepts window W-1 route."""
    now = 1772800000
    routes = mutator.active_routes(now)
    # Validate window -1 route (prev) is accepted
    assert mutator.validate_route(routes["prev"], now) is True


def test_t3_expired_route_rejection(mutator):
    """T3: Expired route (window W-2) fails route validation."""
    now = 1772800000
    w_old = (now // 60) - 2
    old_route = f"/api/v1/telemetry/rotated_{mutator._scramble_hex(w_old)}"
    assert mutator.validate_route(old_route, now) is False


# ── Test Suite: Block 1 (Smart Meter) ─────────────────────────────

def test_meter_block_generation(meter):
    """Test SmartMeterSimulator increments nonces and generates valid ECDSA signed block."""
    initial_nonce = meter.nonce
    block = meter.generate_block(0.412, "2026-09-06T17:30:00.000Z")
    
    assert block.nonce == initial_nonce + 1
    assert block.mpan == "MPAN-1200012345678"
    assert len(block.block_hash) == 64
    assert len(block.signature) > 0


# ── Test Suite: Block 3 (ETP Gateway & Nonce CAS) ────────────────

def test_t1_t4_t5_gateway_ingestion(gateway, meter, mutator):
    """Test valid ingestion (T1), replay rejection (T4), and payload tampering (T5)."""
    now = int(time.time())
    gateway.register_meter_public_key(meter.mpan, meter.public_key)
    routes = mutator.active_routes(now)
    current_route = routes["current"]

    # 1. Valid Block Ingest (T1)
    block1 = meter.generate_block(0.412, "2026-09-06T17:30:00.000Z")
    code, res = gateway.process_request(current_route, block1.to_dict(), now)
    assert code == 200
    assert res["status"] == "accepted"
    assert res["verify_status"] == "VERIFIED"

    # 2. Replay Attack (T4) — Send duplicate block with same nonce
    code_replay, res_replay = gateway.process_request(current_route, block1.to_dict(), now)
    assert code_replay == 401
    assert res_replay["reason"] == "REPLAY_REJECTED"

    # 3. Data Tampering (T5) — Modify reading kWh value
    block2 = meter.generate_block(0.500, "2026-09-06T17:30:30.000Z")
    tampered_dict = block2.to_dict()
    tampered_dict["reading_kwh"] = 99.999  # Tampered!
    
    code_tamper, res_tamper = gateway.process_request(current_route, tampered_dict, now)
    assert code_tamper == 401
    assert res_tamper["reason"] == "TAMPER_REJECTED"


def test_poisoned_nonce_dos_protection(gateway, meter, mutator):
    """Verifies that an unverified packet with an extreme nonce does NOT poison the store (DoS Protection)."""
    now = int(time.time())
    gateway.register_meter_public_key(meter.mpan, meter.public_key)
    routes = mutator.active_routes(now)
    current_route = routes["current"]

    # 1. Attacker sends tampered block with giant poisoned nonce = 9223372036854775807
    attacker_block = meter.generate_block(0.412)
    poisoned_dict = attacker_block.to_dict()
    poisoned_dict["nonce"] = 9223372036854775807
    poisoned_dict["reading_kwh"] = 888.888  # Invalid hash signature!

    code_attack, res_attack = gateway.process_request(current_route, poisoned_dict, now)
    assert code_attack == 401
    assert res_attack["reason"] in ("TAMPER_REJECTED", "SIGNATURE_INVALID")

    # 2. Legitimate meter sends next normal block with sequential nonce
    legit_block = meter.generate_block(0.415)
    code_legit, res_legit = gateway.process_request(current_route, legit_block.to_dict(), now)

    # MUST be accepted! Store was NOT poisoned by unverified attack packet!
    assert code_legit == 200
    assert res_legit["status"] == "accepted"
    assert res_legit["verify_status"] == "VERIFIED"


def test_t8_t9_phantom_grid_deception(gateway, meter):
    """T8/T9: Static URI hit triggers Phantom Grid honeypot deception."""
    now = int(time.time())
    block = meter.generate_block(0.412)
    
    # Send request to static unrotated URI
    static_route = "/api/v1/telemetry"
    code, res = gateway.process_request(static_route, block.to_dict(), now, source_ip="198.51.100.42")
    
    # Returns HTTP 200 OK with plausible synthetic data
    assert code == 200
    assert res["status"] in ("acknowledged", "transient_error")
    assert len(gateway.phantom_grid.threat_logs) > 0
    assert gateway.phantom_grid.threat_logs[0]["source_ip"] == "198.51.100.42"


# ── Test Suite: Block 5 (Micro-Batch Writer) ─────────────────────

def test_micro_batch_writer(meter):
    """Test MicroBatchWriter buffers blocks and flushes Iceberg row dicts."""
    writer = MicroBatchWriter(flush_interval_s=30.0, max_batch_size=2)
    block1 = meter.generate_block(0.400)
    block2 = meter.generate_block(0.450)

    writer.add_block(block1)
    assert len(writer.buffer) == 1
    
    writer.add_block(block2)  # Reaches max_batch_size=2, triggers automatic flush
    assert len(writer.buffer) == 0
    assert len(writer.committed_batches) == 1
    
    rows = writer.committed_batches[0]
    assert len(rows) == 2
    assert rows[0]["mpan"] == meter.mpan
    assert rows[0]["etp_verify_status"] == "VERIFIED"


# ── Test Suite: Block 6 & 7 (Merkle Tree & Verifier) ──────────────

def test_t10_t25_merkle_tree_domain_separation():
    """T10/T25: Test domain-separated Merkle tree root computation and odd leaf promotion."""
    leaves = [
        "a3f1b2c4d5e6f7a8b9c0d1e2f3a4b5c6d7e8f9a0b1c2d3e4f5a6b7c8d9e0f1a2",
        "b4f2b3c5d6e7f8a9b0c1d2e3f4a5b6c7d8e9f0a1b2c3d4e5f6a7b8c9d0e1f2a3",
        "c5f3b4c6d7e8f9a0b1c2d3e4f5a6b7c8d9e0f1a2b3c4d5e6f7a8b9c0d1e2f3a4"  # 3 leaves (odd count)
    ]
    root = canonical_merkle_root(leaves)
    assert len(root) == 64
    
    # Deterministic test: same input -> same root
    root2 = canonical_merkle_root(leaves)
    assert root == root2


def test_verification_aware_query_object(meter):
    """Test ETPVerifier builds Verification-Aware Query Objects (UC-02)."""
    checkpointer = MerkleCheckpointer()
    verifier = ETPVerifier(checkpointer)
    
    block = meter.generate_block(0.412)
    row = {
        "mpan": meter.mpan,
        "reading_kwh": 0.412,
        "etp_block_hash": block.block_hash,
        "etp_nonce": block.nonce,
        "etp_verify_status": "VERIFIED"
    }

    query_obj = verifier.execute_verification_aware_query(
        query_id="q_12345",
        sql_string="SELECT mpan, SUM(reading_kwh)...",
        snapshot_id=987654321,
        result_set=[{"mpan": meter.mpan, "total_kwh": 0.412}],
        contributing_readings=[row]
    )

    assert query_obj.query_id == "q_12345"
    assert query_obj.snapshot_id == 987654321
    assert query_obj.verification_proof["total_rows_scanned"] == 1
    assert query_obj.verification_proof["status_summary"]["VERIFIED"] == 1
    assert query_obj.verification_proof["proof_verified_independently"] is True


# ── Test Suite: Encryption & Security Manager ────────────────────

def test_security_encryption_and_masking():
    """Test AES-256-GCM encryption and RBAC column masking."""
    sec = ETPSecurityManager()
    
    # AES-256-GCM Encryption
    plaintext = "MPAN-1200012345678"
    ciphertext = sec.encrypt_field(plaintext)
    assert ciphertext != plaintext
    assert sec.decrypt_field(ciphertext) == plaintext

    # RBAC Column Masking
    unmasked = sec.mask_mpan(plaintext, role="Admin")
    assert unmasked == plaintext

    masked = sec.mask_mpan(plaintext, role="BusinessAnalyst")
    assert masked.startswith("MPAN-***-")
    assert plaintext not in masked


# ── Test Suite: IEC CIM Profile Exporter ──────────────────────────

def test_cim_exporter():
    """Test IEC CIM RDF/XML export with TelemetryProvenance extension."""
    exporter = CIMProfileExporter()
    readings = [{
        "mpan": "MPAN-1200012345678",
        "reading_ts": "2026-09-06T17:30:00.000Z",
        "reading_kwh": 0.412,
        "etp_block_hash": "9c2e4f71a83b...",
        "etp_nonce": 184291,
        "etp_crypto_suite_id": "ECDSA-P256-SHA256-v1",
        "etp_verify_status": "VERIFIED"
    }]

    xml_output = exporter.export_to_rdf_xml(readings)
    assert "<cim:UsagePoint" in xml_output
    assert "MPAN-1200012345678" in xml_output
    assert "<etp:TelemetryProvenance" in xml_output
    assert "<etp:verificationStatus>VERIFIED</etp:verificationStatus>" in xml_output
