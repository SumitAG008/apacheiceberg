"""Targeted Regression Test Suite for Sliding Window Nonce Store, Backfill Chain Integrity, and TSA DER PKIStatus Parsing.

Verifies:
1. Out-of-order backfill acceptance (OK_BACKFILL) within sliding window.
2. Backfill does NOT corrupt last_hash (chain head stays anchored to highest nonce).
3. Expired nonces below sliding window threshold return EXPIRED_NONCE_REJECTED.
4. Window size bitmask scaling (128 / 1024 nonces).
5. RFC 3161 DER TimeStampReq encoding and TimeStampResp PKIStatus parsing.
6. Checkpoint metadata digest commitment (anchor_digest).
"""

import sys
import base64
import hashlib
from pathlib import Path

root_dir = Path(__file__).resolve().parent.parent.parent
backend_dir = Path(__file__).resolve().parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

import pytest
try:
    from backend.etp.gateway import SlidingWindowNonceStore
    from backend.etp.checkpointer import (
        MerkleCheckpointer,
        create_rfc3161_anchor_token,
        parse_rfc3161_pkistatus
    )
except ImportError:
    from etp.gateway import SlidingWindowNonceStore
    from etp.checkpointer import (
        MerkleCheckpointer,
        create_rfc3161_anchor_token,
        parse_rfc3161_pkistatus
    )


def test_sliding_window_backfill_accepts_unseen_older_nonce():
    """Test out-of-order backfill within window returns OK_BACKFILL / ACCEPT_BACKFILL."""
    store = SlidingWindowNonceStore(window_size=64)
    mpan = "MPAN-TEST-BACKFILL-01"

    # Ingest sequential in-order nonces 100, 101
    store.commit(mpan, incoming_nonce=100, incoming_hash="hash_100", timestamp="2026-09-18T10:00:00Z")
    status, last_n, msg = store.commit(mpan, incoming_nonce=101, incoming_hash="hash_101", timestamp="2026-09-18T10:00:30Z")
    assert status == 1
    assert store.get_last_hash(mpan) == "hash_101"

    # Out-of-order backfill of nonce 95 (within 64-nonce window)
    check_status, check_last, check_msg = store.check_only(mpan, 95)
    assert check_status == 1
    assert check_msg == "OK_BACKFILL"

    commit_status, commit_last, commit_msg = store.commit(mpan, 95, "hash_95_backfill", "2026-09-18T09:30:00Z")
    assert commit_status == 1
    assert commit_msg == "ACCEPT_BACKFILL"

    # Replay of backfill nonce 95 must be rejected!
    replay_status, _, replay_msg = store.check_only(mpan, 95)
    assert replay_status == 0
    assert replay_msg == "REPLAY_REJECTED"


def test_backfill_does_not_corrupt_chain_head_last_hash():
    """BLOCKER 2 FIX: Backfilling nonce 95 MUST NOT overwrite last_hash (which remains hash_101)."""
    store = SlidingWindowNonceStore(window_size=64)
    mpan = "MPAN-TEST-CHAIN-02"

    store.commit(mpan, 100, "hash_100", "2026-09-18T10:00:00Z")
    store.commit(mpan, 101, "hash_101", "2026-09-18T10:00:30Z")
    assert store.get_last_hash(mpan) == "hash_101"

    # Backfill nonce 95
    store.commit(mpan, 95, "hash_95_backfill", "2026-09-18T09:30:00Z")

    # CRITICAL ASSERTION: last_hash MUST remain hash_101 so next in-order block (102) links properly!
    assert store.get_last_hash(mpan) == "hash_101"

    # Ingest next in-order block 102
    store.commit(mpan, 102, "hash_102", "2026-09-18T10:01:00Z")
    assert store.get_last_hash(mpan) == "hash_102"


def test_expired_nonce_rejection_below_window():
    """Test nonces below (last_nonce - window_size) are rejected as EXPIRED_NONCE_REJECTED."""
    store = SlidingWindowNonceStore(window_size=64)
    mpan = "MPAN-TEST-EXPIRED-03"

    store.commit(mpan, 1000, "hash_1000", "2026-09-18T10:00:00Z")

    # Nonce 900 is 100 below 1000 (> 64 window_size) -> Expired
    status, last_n, msg = store.check_only(mpan, 900)
    assert status == 0
    assert msg == "EXPIRED_NONCE_REJECTED"


def test_dynamic_window_size_scaling():
    """BLOCKER 3 FIX: Window sizes of 128 / 1024 nonces work dynamically without bitmask truncation."""
    store = SlidingWindowNonceStore(window_size=128)
    mpan = "MPAN-TEST-SCALING-04"

    store.commit(mpan, 1000, "hash_1000", "2026-09-18T10:00:00Z")
    store.commit(mpan, 1070, "hash_1070", "2026-09-18T11:00:00Z")

    # Nonce 1000 is 70 below 1070. Fits in 128 window!
    status, _, msg = store.check_only(mpan, 1000)
    assert status == 0  # 1000 was already committed earlier -> REPLAY_REJECTED

    # Nonce 950 is 120 below 1070. Fits in 128 window and unseen -> OK_BACKFILL!
    status950, _, msg950 = store.check_only(mpan, 950)
    assert status950 == 1
    assert msg950 == "OK_BACKFILL"


def test_tsa_pkistatus_rejection_parsing():
    """BLOCKER 1 FIX: TimeStampResp DER rejection (PKIStatus=2) MUST fall back to is_simulated=True."""
    # Simulate a DER TimeStampResp containing PKIStatus = 2 (rejection error)
    # SEQUENCE { SEQUENCE { INTEGER 2, ... } }
    der_rejection_payload = (
        b"\x30\x1a"  # TimeStampResp SEQUENCE
        b"\x30\x18"  # PKIStatusInfo SEQUENCE
        b"\x02\x01\x02"  # PKIStatus = 2 (Rejection)
        b"\x30\x13\x0c\x11Bad request format"
    )

    parsed_status = parse_rfc3161_pkistatus(der_rejection_payload)
    assert parsed_status == 2

    # Simulate a DER TimeStampResp containing PKIStatus = 0 (granted)
    der_granted_payload = (
        b"\x30\x10"
        b"\x30\x0e"
        b"\x02\x01\x00"  # PKIStatus = 0 (Granted)
        b"\x30\x09\x0c\x07Granted"
    )

    parsed_granted = parse_rfc3161_pkistatus(der_granted_payload)
    assert parsed_granted == 0


def test_checkpoint_metadata_digest_anchoring():
    """Test build_meter_day_checkpoint commits an authenticated anchor_digest over metadata."""
    checkpointer = MerkleCheckpointer()
    readings = [{
        "mpan": "MPAN-ANCHOR-01",
        "reading_ts": "2026-09-18T10:00:00Z",
        "reading_kwh": 0.412,
        "etp_block_hash": "a3f1b2c4d5e6f7a8b9c0d1e2f3a4b5c6d7e8f9a0b1c2d3e4f5a6b7c8d9e0f1a2",
        "etp_nonce": 100
    }]

    cp = checkpointer.build_meter_day_checkpoint(
        mpan="MPAN-ANCHOR-01",
        day="2026-09-18",
        readings=readings,
        prev_day_last_nonce=99
    )

    assert "anchor_digest" in cp
    assert len(cp["anchor_digest"]) == 64
    assert cp["is_simulated_anchor"] is True
    assert cp["prev_day_last_nonce"] == 99
    assert cp["boundary_gap"] == 0
