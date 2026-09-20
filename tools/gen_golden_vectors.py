#!/usr/bin/env python3
# Copyright (c) 2026 Meldra AI Ltd. All rights reserved.
"""
tools/gen_golden_vectors.py

Generates golden test vectors from the authoritative Python ETP implementation
and saves them to backend/tests/golden_vectors.json.

Prevents hand-written constant errors and guarantees 100% agreement between Python
and C++ test suites.
"""

import sys
import json
from pathlib import Path

# Add project root to sys.path
root_dir = Path(__file__).resolve().parent.parent
backend_dir = root_dir / "backend"
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from backend.etp.meter import compute_canonical_hash
from backend.etp.route_mutator import RouteMutator
from backend.etp.checkpointer import canonical_merkle_root


def generate_golden_vectors() -> dict:
    # Test Inputs
    secret_key = b"0123456789abcdef0123456789abcdef"
    mpan = "MPAN-1200012345678"
    reading_kwh = 12.345
    timestamp = "2026-09-20T23:00:00.000Z"
    prev_hash = "0000000000000000000000000000000000000000000000000000000000000000"
    nonce = 100
    crypto_suite_id = "ECDSA-P256-SHA256-v1"
    key_id = "k-test"
    window = 28333333

    # Computations
    canonical_hash = compute_canonical_hash(
        mpan=mpan,
        reading_kwh=reading_kwh,
        timestamp=timestamp,
        prev_hash=prev_hash,
        nonce=nonce,
        crypto_suite_id=crypto_suite_id,
        key_id=key_id
    )

    mutator = RouteMutator(secret_key=secret_key, window_s=60)
    route_scramble = mutator._scramble_hex(window)

    test_leaves = [
        "0000000000000000000000000000000000000000000000000000000000000001",
        "0000000000000000000000000000000000000000000000000000000000000002"
    ]
    merkle_root = canonical_merkle_root(test_leaves)

    vectors = {
        "version": 1,
        "inputs": {
            "secret_key_hex": secret_key.hex(),
            "mpan": mpan,
            "reading_kwh": reading_kwh,
            "timestamp": timestamp,
            "prev_hash": prev_hash,
            "nonce": nonce,
            "crypto_suite_id": crypto_suite_id,
            "key_id": key_id,
            "window": window,
            "test_leaves": test_leaves
        },
        "expected_outputs": {
            "canonical_hash": canonical_hash,
            "route_scramble": route_scramble,
            "merkle_root": merkle_root
        }
    }
    return vectors


def main():
    vectors = generate_golden_vectors()
    out_path = backend_dir / "tests" / "golden_vectors.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(vectors, f, indent=2)
    print(f"✅ Generated golden test vectors saved to {out_path}")
    print(f"   Canonical Hash : {vectors['expected_outputs']['canonical_hash']}")
    print(f"   Route Scramble : {vectors['expected_outputs']['route_scramble']}")
    print(f"   Merkle Root    : {vectors['expected_outputs']['merkle_root']}")


if __name__ == "__main__":
    main()
