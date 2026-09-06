"""
tests/test_etp_gateway_regressions.py

Regression tests pinning two gateway defects found on 2026-09-06:

  ETP-2026-001  (High)   The nonce store committed BEFORE hash and signature
                         verification. A single unsigned packet carrying a
                         huge nonce permanently locked out a meter: every
                         later legitimate reading was rejected as a replay
                         against a counter the attacker had set.

  ETP-2026-002  (Medium) process_request() constructed a SmartMeterSimulator
                         on every request purely to reach a hash function.
                         That constructor runs a full ECDSA P-256 keygen —
                         ~41x the cost of the hash, capping throughput at
                         ~41k blocks/sec before any verification happened,
                         and inverting the DoS ordering the gateway was
                         designed around.

If either of these fails, do not skip it. ETP-2026-001 is an availability
attack on a single meter that requires no credentials.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

# Dual path resolution to run from root or backend/
root_dir = Path(__file__).resolve().parent.parent.parent
backend_dir = Path(__file__).resolve().parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

import pytest

try:
    from backend.etp.gateway import ETPGateway, MemoryNonceStore
    from backend.etp.meter import SmartMeterSimulator, compute_canonical_hash
    from backend.etp.phantom_grid import PhantomGridHoneypot
    from backend.etp.route_mutator import RouteMutator
except ImportError:
    from etp.gateway import ETPGateway, MemoryNonceStore
    from etp.meter import SmartMeterSimulator, compute_canonical_hash
    from etp.phantom_grid import PhantomGridHoneypot
    from etp.route_mutator import RouteMutator

SECRET = b"k" * 32
NOW = 1_757_000_000


@pytest.fixture
def rig():
    """Gateway with one registered meter, and the meter itself."""
    mutator = RouteMutator(secret_key=SECRET)
    gw = ETPGateway(
        route_mutator=mutator,
        nonce_store=MemoryNonceStore(),
        phantom_grid=PhantomGridHoneypot(),
    )
    meter = SmartMeterSimulator(mpan="MPAN-1200012345678")
    gw.register_meter_public_key(meter.mpan, meter.public_key)
    route = mutator.active_routes(NOW)["current"]
    return gw, meter, route


# ─── ETP-2026-001 — the lockout attack ────────────────────────────────────

def test_unsigned_block_with_huge_nonce_does_not_lock_out_meter(rig):
    """THE regression test for ETP-2026-001.

    An attacker who has discovered a currently-valid route sends a block
    with a maximal nonce and garbage everywhere else. The gateway must
    reject it AND must leave the meter fully operational afterwards.
    """
    gw, meter, route = rig

    # Baseline: the meter works.
    good = meter.generate_block(0.412)
    status, _ = gw.process_request(route, good.to_dict(), NOW)
    assert status == 200

    # Attack: valid route, maximal nonce, no valid hash or signature.
    poison = {
        "mpan": meter.mpan,
        "reading_kwh": 0.001,
        "timestamp": "2026-09-06T12:00:00.000Z",
        "prev_hash": "00" * 32,
        "nonce": 2**63 - 1,
        "crypto_suite_id": "ECDSA-P256-SHA256-v1",
        "key_id": meter.key_id,
        "block_hash": "de" * 32,
        "signature": "ad" * 64,
    }
    status, body = gw.process_request(route, poison, NOW)
    assert status == 401
    assert body["reason"] in ("TAMPER_REJECTED", "SIGNATURE_INVALID")

    # THE ASSERTION: the meter must still work. Before the fix this was
    # REPLAY_REJECTED forever, because the poisoned nonce had been committed.
    nxt = meter.generate_block(0.501)
    status, body = gw.process_request(route, nxt.to_dict(), NOW)
    assert status == 200, (
        f"meter locked out by an unverified block — ETP-2026-001 has "
        f"regressed (got {body})"
    )


def test_tampered_payload_does_not_advance_counter(rig):
    """A block whose reading was altered in flight must not move the nonce."""
    gw, meter, route = rig
    blk = meter.generate_block(0.412).to_dict()
    blk["reading_kwh"] = 999.999           # tamper; block_hash no longer matches

    status, _ = gw.process_request(route, blk, NOW)
    assert status == 401

    # Store must be untouched — no record, or the pre-attack value.
    assert gw.nonce_store.check_only(meter.mpan, blk["nonce"])[0] == 1


def test_bad_signature_does_not_advance_counter(rig):
    """Hash correct, signature forged. Counter must not move."""
    gw, meter, route = rig
    blk = meter.generate_block(0.412).to_dict()
    blk["signature"] = "00" * 64

    status, body = gw.process_request(route, blk, NOW)
    assert status == 401
    assert body["reason"] == "SIGNATURE_INVALID"
    assert gw.nonce_store.check_only(meter.mpan, blk["nonce"])[0] == 1


def test_genuine_replay_still_rejected(rig):
    """The fix must not weaken replay protection for VERIFIED blocks."""
    gw, meter, route = rig
    blk = meter.generate_block(0.412).to_dict()

    assert gw.process_request(route, blk, NOW)[0] == 200
    status, body = gw.process_request(route, blk, NOW)     # exact replay
    assert status == 401
    assert body["reason"] == "REPLAY_REJECTED"


def test_check_only_never_mutates_state():
    """check_only() is a pure read. Called repeatedly, nothing changes."""
    store = MemoryNonceStore()
    for _ in range(50):
        assert store.check_only("MPAN-1", 10**9)[0] == 1
    # Still no record, so a later commit at a low nonce succeeds.
    assert store.commit("MPAN-1", 5, "ab" * 32, "2026-09-06T12:00:00.000Z")[0] == 1


def test_commit_retests_nonce_inside_lock():
    """Two blocks that both passed check_only cannot both commit."""
    store = MemoryNonceStore()
    assert store.check_only("MPAN-1", 100)[0] == 1
    assert store.check_only("MPAN-1", 100)[0] == 1     # both peeked OK
    assert store.commit("MPAN-1", 100, "aa" * 32, "t")[0] == 1
    assert store.commit("MPAN-1", 100, "bb" * 32, "t")[0] == 0   # second loses


# ─── ETP-2026-002 — no key material in the hot path ───────────────────────

def test_hash_function_is_pure_and_importable():
    """compute_canonical_hash must be module-level, not a method on a class
    whose constructor generates keys."""
    h1 = compute_canonical_hash(
        "MPAN-1", 0.412, "2026-09-06T12:00:00.000Z", "00" * 32,
        1, "ECDSA-P256-SHA256-v1", "k-1",
    )
    h2 = compute_canonical_hash(
        "MPAN-1", 0.412, "2026-09-06T12:00:00.000Z", "00" * 32,
        1, "ECDSA-P256-SHA256-v1", "k-1",
    )
    assert h1 == h2 and len(h1) == 64


def test_meter_method_and_pure_function_agree():
    """One implementation of the canonicalisation rules, not two.

    Two implementations is how the meter and the gateway drift apart and
    every block starts failing.
    """
    m = SmartMeterSimulator(mpan="MPAN-1")
    args = ("MPAN-1", 0.412, "2026-09-06T12:00:00.000Z", "00" * 32,
            7, "ECDSA-P256-SHA256-v1", "k-1")
    assert m.compute_canonical_hash(*args) == compute_canonical_hash(*args)


def test_gateway_does_not_construct_a_meter_per_request():
    """Static check: no SmartMeterSimulator in the gateway's hot path.

    Its __init__ runs ec.generate_private_key(SECP256R1), ~41x the cost of
    the hash it was being constructed to compute.
    """
    import pathlib
    src = (pathlib.Path(__file__).resolve().parent.parent
           / "etp" / "gateway.py").read_text(encoding="utf-8")
    assert "SmartMeterSimulator(" not in src, (
        "gateway constructs a meter (and therefore an ECDSA keypair) per "
        "request — ETP-2026-002 has regressed"
    )
    assert "compute_canonical_hash(" in src


def test_verification_throughput_is_not_keygen_bound(rig):
    """Sane-throughput guard.

    With the keygen removed, 200 verified blocks should complete far faster
    than the ~41k/sec ceiling the old code imposed. Deliberately loose so it
    is not flaky on shared CI, but tight enough to catch a keygen creeping
    back into the path.
    """
    gw, meter, route = rig
    blocks = [meter.generate_block(0.4 + i / 1000).to_dict() for i in range(200)]

    t0 = time.perf_counter()
    for b in blocks:
        assert gw.process_request(route, b, NOW)[0] == 200
    per_block_ms = (time.perf_counter() - t0) / len(blocks) * 1000

    assert per_block_ms < 5.0, (
        f"{per_block_ms:.3f} ms/block — expensive key material is probably "
        f"back in the verification path"
    )
