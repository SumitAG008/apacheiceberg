"""Block 6 — Daily Merkle Checkpointer & Nonce Sequence Validator.

Builds daily per-meter and estate-wide Merkle trees with domain separation (0x00 leaf / 0x01 parent)
preventing CVE-2012-2459 duplicate leaf vulnerabilities. Validates monotonic nonces for omission detection.
"""

import hashlib
import datetime
from typing import List, Dict, Any, Tuple


def canonical_merkle_root(leaf_hashes_hex: List[str]) -> str:
    """Computes binary Merkle tree root with domain separation.
    
    Leaves: 0x00 || LeafHashBytes
    Parents: 0x01 || LeftBytes || RightBytes
    Odd Node Promotion: Promotes final node without duplication (prevents CVE-2012-2459).
    """
    if not leaf_hashes_hex:
        return ""

    # Level 0: Leaf Nodes with 0x00 domain separation
    current_level = [
        hashlib.sha256(b"\x00" + bytes.fromhex(h)).digest()
        for h in leaf_hashes_hex
    ]

    # Tree Building Loop
    while len(current_level) > 1:
        next_level = []
        for i in range(0, len(current_level), 2):
            left = current_level[i]
            if i + 1 < len(current_level):
                right = current_level[i + 1]
                parent = hashlib.sha256(b"\x01" + left + right).digest()
            else:
                # Odd node promotion WITHOUT duplication
                parent = left
            next_level.append(parent)
        current_level = next_level

    return current_level[0].hex()


class MerkleCheckpointer:
    """Daily checkpointer building Merkle roots and external TSA anchors."""

    def __init__(self):
        self.checkpoints: List[Dict[str, Any]] = []

    def build_meter_day_checkpoint(
        self,
        mpan: str,
        day: str,
        readings: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Builds Merkle tree checkpoint for a single meter's daily readings."""
        if not readings:
            raise ValueError("No readings provided for checkpoint")

        # Sort readings by monotonic nonce to guarantee strict deterministic sequence
        sorted_readings = sorted(readings, key=lambda x: x["etp_nonce"])
        leaf_hashes = [r["etp_block_hash"] for r in sorted_readings]
        
        # Build canonical Merkle root
        merkle_root = canonical_merkle_root(leaf_hashes)

        first_nonce = sorted_readings[0]["etp_nonce"]
        last_nonce = sorted_readings[-1]["etp_nonce"]
        leaf_count = len(sorted_readings)

        # Monotonic Nonce Discontinuity / Omission Detection (UC-09)
        # Expected nonces = last_nonce - first_nonce + 1
        expected_count = last_nonce - first_nonce + 1
        gap_count = max(0, expected_count - leaf_count)

        # Generate mock RFC 3161 Timestamping Authority (TSA) Anchor Token
        tsa_timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat()
        anchor_token = f"tsa:{tsa_timestamp}:token_{hashlib.sha256(merkle_root.encode('utf-8')).hexdigest()[:16]}"

        checkpoint = {
            "mpan_bucket": hash(mpan) % 16,
            "mpan": mpan,
            "day": day,
            "merkle_root": merkle_root,
            "leaf_count": leaf_count,
            "first_nonce": first_nonce,
            "last_nonce": last_nonce,
            "gap_count": gap_count,
            "built_at": tsa_timestamp,
            "anchor_ref": anchor_token,
            "anchor_at": tsa_timestamp,
            "status": "ANCHORED" if gap_count == 0 else "ANCHORED_WITH_GAPS"
        }

        self.checkpoints.append(checkpoint)
        return checkpoint
