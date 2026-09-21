"""Differential & Adversarial Verification Suite: C++ Native Engine (etp_core_cpp) vs Python Reference.

Tests byte-for-byte and hash-for-hash parity across boundary conditions:
- Float rounding boundary cases (0.4125, 0.4135, 2.5e-4)
- Signed zero (-0.0 -> "0.000")
- Boundary nonces (0 and 2^64 - 1)
- Non-ASCII and empty MPAN strings
- Merkle trees of sizes 0, 1, 2, 3, 47, 48, 49 (odd node promotion validation)
- Directional Merkle proofs (MerkleProofStep is_left)
"""

import pytest
import os
import hashlib
import sys
backend_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if backend_path not in sys.path:
    sys.path.insert(0, backend_path)

from etp.meter import compute_canonical_hash
from etp.route_mutator import RouteMutator
from etp.checkpointer import canonical_merkle_root, verify_merkle_proof

try:
    import etp_core_cpp
    HAS_CPP = True
except ImportError:
    HAS_CPP = False


def test_cpp_module_loaded_explicitly():
    """Asserts that C++ native extension is present and exposed."""
    assert HAS_CPP, "etp_core_cpp extension module is not installed or imported"
    assert hasattr(etp_core_cpp, "GatewayEngine")
    assert hasattr(etp_core_cpp, "RouteMutator")
    assert hasattr(etp_core_cpp, "MerkleTree")
    assert hasattr(etp_core_cpp, "MerkleProofStep")


def test_adversarial_canonical_hash_boundary_cases():
    """Tests compute_canonical_hash against float ties, negative zero, boundary nonces, and non-ASCII MPANs."""
    test_cases = [
        # (mpan, reading_kwh, timestamp, prev_hash, nonce, suite, key_id)
        ("MPAN-1001", 0.4125, "2026-09-20T23:00:00.000Z", "0" * 64, 100, "ECDSA-P256-SHA256-v1", "k-1"),
        ("MPAN-1002", 0.4135, "2026-09-20T23:00:00.000Z", "0" * 64, 101, "ECDSA-P256-SHA256-v1", "k-2"),
        ("MPAN-1003", 2.5e-4, "2026-09-20T23:00:00.000Z", "0" * 64, 102, "ECDSA-P256-SHA256-v1", "k-3"),
        ("MPAN-ZERO", -0.0, "2026-09-20T23:00:00.000Z", "0" * 64, 0, "ECDSA-P256-SHA256-v1", "k-4"),
        ("MPAN-MAX-NONCE", 123.456, "2026-09-20T23:00:00.000Z", "f" * 64, 18446744073709551615, "ECDSA-P256-SHA256-v1", "k-max"),
        ("MPAN-⚡-NONASCII", 99.999, "2026-09-20T23:00:00.000Z", "a" * 64, 500, "ECDSA-P256-SHA256-v1", "k-unicode"),
        ("", 0.0, "2026-09-20T23:00:00.000Z", "0" * 64, 1, "ECDSA-P256-SHA256-v1", ""),
    ]

    for mpan, kwh, ts, prev, nonce, suite, key_id in test_cases:
        py_hash = compute_canonical_hash(mpan, kwh, ts, prev, nonce, suite, key_id)
        assert len(py_hash) == 64
        
        if HAS_CPP:
            b = etp_core_cpp.TelemetryBlock()
            b.mpan = mpan
            b.reading_kwh = float(kwh)
            b.timestamp = ts
            b.prev_hash = prev
            b.nonce = int(nonce)
            b.crypto_suite_id = suite
            b.key_id = key_id
            cpp_hash = etp_core_cpp.GatewayEngine.compute_canonical_hash(b)
            assert cpp_hash == py_hash, f"Hash mismatch for MPAN '{mpan}', kwh={kwh}, nonce={nonce}"


def test_adversarial_merkle_tree_leaf_counts():
    """Tests Merkle tree root parity across leaf counts 0, 1, 2, 3, 47, 48, 49."""
    counts = [0, 1, 2, 3, 47, 48, 49]
    
    for count in counts:
        leaves = [hashlib.sha256(f"leaf_{i}".encode('utf-8')).hexdigest() for i in range(count)]
        py_root = canonical_merkle_root(leaves)
        
        if HAS_CPP:
            tree = etp_core_cpp.MerkleTree()
            for h in leaves:
                tree.add_leaf_hex(h)
            cpp_root = tree.compute_root()
            assert cpp_root == py_root, f"Merkle root mismatch for {count} leaves: cpp='{cpp_root}', py='{py_root}'"


def test_adversarial_merkle_proofs():
    """Tests directional Merkle proof generation and verification across C++ and Python."""
    leaves = [hashlib.sha256(f"leaf_{i}".encode('utf-8')).hexdigest() for i in range(5)]
    root = canonical_merkle_root(leaves)

    if HAS_CPP:
        tree = etp_core_cpp.MerkleTree()
        for h in leaves:
            tree.add_leaf_hex(h)
        assert tree.compute_root() == root

        for idx in range(len(leaves)):
            proof = tree.get_proof(idx)
            # Convert proof to dict list for verify_merkle_proof
            proof_dicts = [{"hash": step.hash, "is_left": step.is_left} for step in proof]
            
            # Verify using C++ and Python wrapper
            assert verify_merkle_proof(leaves[idx], proof_dicts, root), f"Proof failed for leaf index {idx}"
            assert etp_core_cpp.MerkleTree.verify_proof(leaves[idx], proof, root), f"Native C++ proof failed for leaf index {idx}"


def test_adversarial_route_mutator():
    """Tests RouteMutator MTD scrambling parity."""
    secret = b"0123456789abcdef0123456789abcdef"
    py_mutator = RouteMutator(secret, window_s=60, base_uri="/api/v1/telemetry")
    now = 1700000000

    routes = py_mutator.active_routes(now)
    assert py_mutator.validate_route(routes["current"], now)
    assert py_mutator.validate_route(routes["prev"], now)
    assert py_mutator.validate_route(routes["next"], now)
    assert not py_mutator.validate_route("/api/v1/telemetry/rotated_badhex12", now)

    if HAS_CPP:
        secret_str = secret.decode('latin1')
        cpp_mutator = etp_core_cpp.RouteMutator(secret_str, 60, "/api/v1/telemetry")
        cpp_routes = cpp_mutator.get_routes(now)
        
        assert cpp_routes.current_route == routes["current"]
        assert cpp_routes.prev_route == routes["prev"]
        assert cpp_routes.next_route == routes["next"]
        assert cpp_mutator.validate_route(routes["current"], now)
        assert not cpp_mutator.validate_route("/api/v1/telemetry/rotated_badhex12", now)
