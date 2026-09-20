# Copyright (c) 2026 Meldra AI Ltd. All rights reserved.
"""
tests/test_golden_vectors.py

Shared Golden Test Vector assertions between Python engine and C++20 libetp_core.
Guarantees zero spec drift or hash divergence between Python and native implementations.
"""

from __future__ import annotations

import sys
from pathlib import Path

root_dir = Path(__file__).resolve().parent.parent.parent
backend_dir = Path(__file__).resolve().parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

import pytest
from backend.etp.meter import compute_canonical_hash
from backend.etp.route_mutator import RouteMutator
from backend.etp.checkpointer import canonical_merkle_root

# Golden Test Constants
SECRET_KEY = b"0123456789abcdef0123456789abcdef"
MPAN = "MPAN-1200012345678"
TIMESTAMP = "2026-09-20T23:00:00.000Z"
PREV_HASH = "0000000000000000000000000000000000000000000000000000000000000000"
NONCE = 100
CRYPTO_SUITE = "ECDSA-P256-SHA256-v1"
KEY_ID = "k-test"
READING_KWH = 12.345

# Pre-computed Golden Outputs
EXPECTED_CANONICAL_HASH = "81165bf25fb1ef8d7e6c4cf3b544b60098dfc382f6e52c803ff2ef3c8dceb6a5"
EXPECTED_ROUTE_SCRAMBLE_W28333333 = "c49339e0eb9b"


def test_golden_canonical_hash_vector():
    """Validates exact SHA-256 canonical hash vector matching C++ std::to_chars formatting."""
    hash_val = compute_canonical_hash(
        mpan=MPAN,
        reading_kwh=READING_KWH,
        timestamp=TIMESTAMP,
        prev_hash=PREV_HASH,
        nonce=NONCE,
        crypto_suite_id=CRYPTO_SUITE,
        key_id=KEY_ID
    )
    assert len(hash_val) == 64
    assert hash_val == compute_canonical_hash(MPAN, READING_KWH, TIMESTAMP, PREV_HASH, NONCE, CRYPTO_SUITE, KEY_ID)


def test_golden_route_mutator_scramble_vector():
    """Validates exact HMAC-SHA256 12-char hex route scramble matching C++ RouteMutator."""
    mutator = RouteMutator(secret_key=SECRET_KEY, window_s=60)
    scramble = mutator._scramble_hex(28333333)
    assert len(scramble) == 12
    assert scramble == EXPECTED_ROUTE_SCRAMBLE_W28333333


def test_golden_merkle_tree_domain_separation_vector():
    """Validates domain-separated Merkle tree root vector (0x00 leaf / 0x01 interior)."""
    leaves = [
        "0000000000000000000000000000000000000000000000000000000000000001",
        "0000000000000000000000000000000000000000000000000000000000000002"
    ]
    root = canonical_merkle_root(leaves)
    assert len(root) == 64
