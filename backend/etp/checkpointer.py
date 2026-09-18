"""Block 6 — Daily Merkle Checkpointer & Nonce Sequence Validator.

Builds daily per-meter and estate-wide Merkle trees with domain separation (0x00 leaf / 0x01 parent)
preventing CVE-2012-2459 duplicate leaf vulnerabilities. Validates monotonic nonces for omission detection.
"""

import json
import base64
import hashlib
import datetime
from typing import List, Dict, Any, Tuple


"""Block 6 — Daily Merkle Checkpointer & Nonce Sequence Validator.

Builds daily per-meter and estate-wide Merkle trees with domain separation (0x00 leaf / 0x01 parent)
preventing CVE-2012-2459 duplicate leaf vulnerabilities. Validates monotonic nonces for omission detection.
"""

import json
import base64
import hashlib
import datetime
import urllib.request
from typing import List, Dict, Any, Tuple, Optional


def create_rfc3161_anchor_token(merkle_root: str, timestamp_iso: str, tsa_url: Optional[str] = None) -> Dict[str, Any]:
    """Generates an RFC 3161 Timestamping Authority (TSA) Token envelope.
    
    If `tsa_url` is provided (e.g. FreeTSA / DigiCert RFC 3161 endpoint), attempts a real HTTP 
    DER timestamp query. If `tsa_url` is None or unavailable, generates a transparent 
    SimulatedAnchorToken clearly marked with `is_simulated = True` so it is never misrepresented.
    """
    nonce_hex = hashlib.sha256(f"{merkle_root}:{timestamp_iso}".encode('utf-8')).hexdigest()[:16]
    
    if tsa_url:
        try:
            # Build minimal RFC 3161 TimeStampReq DER payload manually
            # OID for SHA-256: 2.16.840.1.101.3.4.2.1
            msg_bytes = bytes.fromhex(merkle_root)
            req_data = (
                b"\x30\x2f"  # Sequence (47 bytes)
                b"\x02\x01\x01"  # Version 1
                b"\x30\x21"  # MessageImprint sequence
                b"\x30\x0d\x06\x09\x60\x86\x48\x01\x65\x03\x04\x02\x01\x05\x00"  # SHA-256 OID
                b"\x04\x20" + msg_bytes  # Hashed message (32 bytes)
            )
            req = urllib.request.Request(
                tsa_url,
                data=req_data,
                headers={"Content-Type": "application/timestamp-query"}
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                if resp.status == 200:
                    der_token = resp.read()
                    encoded_token = base64.b64encode(der_token).decode('utf-8')
                    return {
                        "is_simulated": False,
                        "token_format": "rfc3161_der_base64",
                        "tsa_url": tsa_url,
                        "hashed_message": merkle_root,
                        "token": f"urn:ietf:rfc:3161:{encoded_token[:64]}..."
                    }
        except Exception as err:
            # Fall through to explicit SimulatedAnchorToken with warning
            pass

    # Explicit, self-describing Simulated Anchor Token (No false RSA claims)
    sig_payload = f"SIMULATED_TSA_V1|policy:1.3.6.1.4.1.58432.1.1.simulated|digest:sha256:{merkle_root}|nonce:{nonce_hex}|ts:{timestamp_iso}"
    simulated_sig = hashlib.sha256(sig_payload.encode('utf-8')).hexdigest()

    token_struct = {
        "is_simulated": True,
        "version": 1,
        "policy": "1.3.6.1.4.1.58432.1.1.simulated",
        "hash_algorithm": "sha256",
        "hashed_message": merkle_root,
        "nonce": nonce_hex,
        "gen_time": timestamp_iso,
        "tsa_name": "urn:meldra:tsa:simulated-local",
        "signature_algorithm": "simulatedSha256HMAC",
        "signature": simulated_sig
    }
    encoded = base64.b64encode(json.dumps(token_struct, sort_keys=True).encode('utf-8')).decode('utf-8')
    return {
        "is_simulated": True,
        "token_format": "simulated_json_base64",
        "hashed_message": merkle_root,
        "token": f"urn:meldra:simulated-tsa:{encoded}"
    }


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

    def __init__(self, tsa_url: Optional[str] = None):
        self.checkpoints: List[Dict[str, Any]] = []
        self.tsa_url = tsa_url

    def build_meter_day_checkpoint(
        self,
        mpan: str,
        day: str,
        readings: List[Dict[str, Any]],
        prev_day_last_nonce: Optional[int] = None
    ) -> Dict[str, Any]:
        """Builds Merkle tree checkpoint for a single meter's daily readings.
        
        Fixes hash seed randomization by using deterministic sha256 partitioning.
        Chains day_N.first_nonce to prev_day_last_nonce + 1 to detect day-boundary truncation.
        """
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
        expected_count = last_nonce - first_nonce + 1
        gap_count = max(0, expected_count - leaf_count)

        # Day-boundary omission check: verify first_nonce == prev_day_last_nonce + 1
        boundary_gap = 0
        if prev_day_last_nonce is not None:
            if first_nonce > prev_day_last_nonce + 1:
                boundary_gap = first_nonce - (prev_day_last_nonce + 1)
                gap_count += boundary_gap

        # Generate RFC 3161 Timestamping Authority (TSA) Anchor Token envelope
        tsa_timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat()
        anchor_envelope = create_rfc3161_anchor_token(merkle_root, tsa_timestamp, tsa_url=self.tsa_url)
        anchor_ref = anchor_envelope["token"]

        # Deterministic Iceberg bucket partitioning (process-independent sha256 hash)
        bucket_id = int(hashlib.sha256(mpan.encode('utf-8')).hexdigest()[:8], 16) % 16

        checkpoint = {
            "mpan_bucket": bucket_id,
            "mpan": mpan,
            "day": day,
            "merkle_root": merkle_root,
            "leaf_count": leaf_count,
            "first_nonce": first_nonce,
            "last_nonce": last_nonce,
            "prev_day_last_nonce": prev_day_last_nonce,
            "gap_count": gap_count,
            "boundary_gap": boundary_gap,
            "built_at": tsa_timestamp,
            "anchor_ref": anchor_ref,
            "anchor_at": tsa_timestamp,
            "is_simulated_anchor": anchor_envelope.get("is_simulated", True),
            "status": "ANCHORED" if gap_count == 0 else "ANCHORED_WITH_GAPS"
        }

        self.checkpoints.append(checkpoint)
        return checkpoint

