"""Block 6 — Daily Merkle Checkpointer & Nonce Sequence Validator.

Builds daily per-meter and estate-wide Merkle trees with domain separation (0x00 leaf / 0x01 parent)
preventing CVE-2012-2459 duplicate leaf vulnerabilities. Validates monotonic nonces for omission detection.
"""

import os
import json
import base64
import hashlib
import logging
import datetime
import urllib.request
from pathlib import Path
from typing import List, Dict, Any, Tuple, Optional

logger = logging.getLogger(__name__)

try:
    import etp_core_cpp
    HAS_CPP_CORE = True
except ImportError as err:
    HAS_CPP_CORE = False
    env = os.getenv("ENVIRONMENT", "production")
    allow_fallback = os.getenv("ETP_ALLOW_PYTHON_FALLBACK", "0") == "1"
    logger.error("Failed to import native C++ etp_core_cpp engine in checkpointer.py: %s", err)
    if env != "development" and not allow_fallback:
        raise RuntimeError(
            f"Native etp_core_cpp module is required in environment='{env}'. "
            "Set ETP_ALLOW_PYTHON_FALLBACK=1 to override in non-production environments."
        ) from err


def parse_rfc3161_pkistatus(der_bytes: bytes) -> Optional[int]:
    """Parses PKIStatus integer from a binary RFC 3161 TimeStampResp DER payload.
    
    Returns:
        0 (granted), 1 (grantedWithMods), 2..5 (rejections), or None if parsing fails.
    """
    try:
        if not der_bytes or der_bytes[0] != 0x30:
            return None
        
        # Parse TimeStampResp SEQUENCE length
        pos = 1
        if der_bytes[pos] & 0x80:
            len_bytes_count = der_bytes[pos] & 0x7f
            pos += 1 + len_bytes_count
        else:
            pos += 1

        # Check status SEQUENCE tag (0x30)
        if pos >= len(der_bytes) or der_bytes[pos] != 0x30:
            return None
        pos += 1
        if der_bytes[pos] & 0x80:
            len_bytes_count = der_bytes[pos] & 0x7f
            pos += 1 + len_bytes_count
        else:
            pos += 1

        # Check PKIStatus INTEGER tag (0x02)
        if pos >= len(der_bytes) or der_bytes[pos] != 0x02:
            return None
        pos += 1
        int_len = der_bytes[pos]
        pos += 1
        
        status_val = int.from_bytes(der_bytes[pos:pos + int_len], byteorder='big')
        return status_val
    except Exception as err:
        logger.warning("Failed to parse RFC 3161 PKIStatus: %s", err)
        return None


def create_rfc3161_anchor_token(anchor_digest: str, timestamp_iso: str, tsa_url: Optional[str] = None) -> Dict[str, Any]:
    """Generates an RFC 3161 Timestamping Authority (TSA) Token envelope.
    
    Fixes Blocker 1:
    - Constructs valid DER TimeStampReq with correct ASN.1 SEQUENCE lengths (30 36 header, 30 31 imprint).
    - Parses PKIStatus from TimeStampResp DER bytes. Sets `is_simulated = False` ONLY if PKIStatus is 0 or 1.
    - Retains full Base64 DER token without string truncation.
    - If tsa_url is None, unavailable, or rejected by TSA, falls back honestly to SimulatedAnchorToken.
    """
    nonce_bytes = hashlib.sha256(f"{anchor_digest}:{timestamp_iso}".encode('utf-8')).digest()[:8]
    nonce_hex = nonce_bytes.hex()
    
    if tsa_url:
        try:
            # Build valid RFC 3161 TimeStampReq DER payload
            # MessageImprint: AlgorithmIdentifier (SHA-256) + HashedMessage (32 bytes) = 49 bytes (0x31)
            msg_bytes = bytes.fromhex(anchor_digest)
            imprint_seq = b"\x30\x31\x30\x0d\x06\x09\x60\x86\x48\x01\x65\x03\x04\x02\x01\x05\x00\x04\x20" + msg_bytes
            version_int = b"\x02\x01\x01"
            cert_req = b"\x01\x01\xff"  # certReq TRUE
            
            req_body = version_int + imprint_seq + cert_req
            # TimeStampReq SEQUENCE: tag 0x30, length = len(req_body) (57 bytes -> 0x39)
            req_data = bytes([0x30, len(req_body)]) + req_body

            req = urllib.request.Request(
                tsa_url,
                data=req_data,
                headers={"Content-Type": "application/timestamp-query"}
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                if resp.status == 200:
                    der_token = resp.read()
                    pki_status = parse_rfc3161_pkistatus(der_token)
                    
                    # ONLY PKIStatus 0 (granted) or 1 (grantedWithMods) are valid TSA proofs
                    if pki_status in (0, 1):
                        encoded_token = base64.b64encode(der_token).decode('utf-8')
                        return {
                            "is_simulated": False,
                            "token_format": "rfc3161_der_base64",
                            "tsa_url": tsa_url,
                            "pki_status": pki_status,
                            "hashed_message": anchor_digest,
                            "token": f"urn:ietf:rfc:3161:{encoded_token}"  # Full token, no truncation
                        }
                    else:
                        logger.warning("TSA returned rejection status PKIStatus=%s from %s", pki_status, tsa_url)
        except Exception as err:
            logger.warning("TSA request to %s failed: %s", tsa_url, err)

    # Explicit, self-describing Simulated Anchor Token (No false RSA claims)
    sig_payload = f"SIMULATED_TSA_V1|policy:1.3.6.1.4.1.58432.1.1.simulated|digest:sha256:{anchor_digest}|nonce:{nonce_hex}|ts:{timestamp_iso}"
    simulated_sig = hashlib.sha256(sig_payload.encode('utf-8')).hexdigest()

    token_struct = {
        "is_simulated": True,
        "version": 1,
        "policy": "1.3.6.1.4.1.58432.1.1.simulated",
        "hash_algorithm": "sha256",
        "hashed_message": anchor_digest,
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
        "hashed_message": anchor_digest,
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

    if HAS_CPP_CORE:
        tree = etp_core_cpp.MerkleTree()
        for h in leaf_hashes_hex:
            tree.add_leaf_hex(h)
        return tree.compute_root()

    # Pure-Python reference fallback
    current_level = [
        hashlib.sha256(b"\x00" + bytes.fromhex(h)).digest()
        for h in leaf_hashes_hex
    ]

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


def verify_merkle_proof(leaf_hash_hex: str, proof: List[Dict[str, Any]], root_hex: str) -> bool:
    """Verifies a directional Merkle proof against a root digest."""
    if HAS_CPP_CORE:
        cpp_proof = []
        for step in proof:
            s = etp_core_cpp.MerkleProofStep()
            s.hash = step["hash"]
            s.is_left = step["is_left"]
            cpp_proof.append(s)
        return etp_core_cpp.MerkleTree.verify_proof(leaf_hash_hex, cpp_proof, root_hex)

    # Pure-Python reference fallback
    current = hashlib.sha256(b"\x00" + bytes.fromhex(leaf_hash_hex)).digest()
    for step in proof:
        sibling = bytes.fromhex(step["hash"])
        if step["is_left"]:
            current = hashlib.sha256(b"\x01" + sibling + current).digest()
        else:
            current = hashlib.sha256(b"\x01" + current + sibling).digest()
    return current.hex() == root_hex


class MerkleCheckpointer:
    """Daily checkpointer building Merkle roots and external TSA anchors with process persistence."""

    def __init__(self, tsa_url: Optional[str] = None, storage_path: Optional[str] = None):
        self.tsa_url = tsa_url
        self.storage_path = storage_path or "backend/data/etp_checkpoints.json"
        self.checkpoints: List[Dict[str, Any]] = []
        self._load_checkpoints()

    def _load_checkpoints(self) -> None:
        """Loads checkpoints from disk to guarantee persistence across process restarts."""
        try:
            path = Path(self.storage_path)
            if path.exists():
                with open(path, "r", encoding="utf-8") as f:
                    self.checkpoints = json.load(f)
                logger.info("Loaded %d ETP checkpoints from %s", len(self.checkpoints), self.storage_path)
        except Exception as err:
            logger.warning("Failed to load checkpoints from %s: %s", self.storage_path, err)
            self.checkpoints = []

    def _save_checkpoints(self) -> None:
        """Persists checkpoints to file storage."""
        try:
            path = Path(self.storage_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(self.checkpoints, f, indent=2)
        except Exception as err:
            logger.warning("Failed to persist checkpoints to %s: %s", self.storage_path, err)

    def build_meter_day_checkpoint(
        self,
        mpan: str,
        day: str,
        readings: List[Dict[str, Any]],
        prev_day_last_nonce: Optional[int] = None,
        expected_daily_readings: Optional[int] = None
    ) -> Dict[str, Any]:
        """Builds Merkle tree checkpoint for a single meter's daily readings.
        
        Anchors over a combined metadata digest (merkle_root + first_nonce + last_nonce + gap_count)
        so checkpoint nonces are cryptographically authenticated against tampering. Includes
        same-day end-of-day truncation detection for half-hourly smart meter readings (48 readings/day).
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
        internal_gap = max(0, (last_nonce - first_nonce + 1) - leaf_count)

        # Day-boundary omission check: verify first_nonce == prev_day_last_nonce + 1
        boundary_gap = 0
        if prev_day_last_nonce is not None:
            if first_nonce > prev_day_last_nonce + 1:
                boundary_gap = first_nonce - (prev_day_last_nonce + 1)

        # Same-day End-of-Day Truncation Check: detect trailing omitted nonces after last_nonce
        eod_gap = 0
        if expected_daily_readings is not None and expected_daily_readings > 0:
            expected_end_nonce = first_nonce + expected_daily_readings - 1
            if expected_end_nonce > last_nonce:
                eod_gap = expected_end_nonce - last_nonce

        gap_count = internal_gap + boundary_gap + eod_gap

        # Authenticated Metadata Commitment (anchors root + nonces + boundary links together)
        anchor_digest = hashlib.sha256(
            f"{merkle_root}|{first_nonce}|{last_nonce}|{leaf_count}|{prev_day_last_nonce}|{eod_gap}".encode('utf-8')
        ).hexdigest()

        # Generate RFC 3161 Timestamping Authority (TSA) Anchor Token envelope
        tsa_timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat()
        anchor_envelope = create_rfc3161_anchor_token(anchor_digest, tsa_timestamp, tsa_url=self.tsa_url)
        anchor_ref = anchor_envelope["token"]

        # Deterministic Iceberg bucket partitioning (process-independent sha256 hash)
        bucket_id = int(hashlib.sha256(mpan.encode('utf-8')).hexdigest()[:8], 16) % 16

        status = "ANCHORED" if gap_count == 0 else "ANCHORED_WITH_GAPS"
        is_simulated = anchor_envelope.get("is_simulated", True)

        checkpoint = {
            "mpan_bucket": bucket_id,
            "mpan": mpan,
            "day": day,
            "merkle_root": merkle_root,
            "anchor_digest": anchor_digest,
            "leaf_count": leaf_count,
            "first_nonce": first_nonce,
            "last_nonce": last_nonce,
            "prev_day_last_nonce": prev_day_last_nonce,
            "gap_count": gap_count,
            "boundary_gap": boundary_gap,
            "eod_gap": eod_gap,
            "built_at": tsa_timestamp,
            "anchor_ref": anchor_ref,
            "anchor_at": tsa_timestamp,
            "is_simulated_anchor": is_simulated,
            "status": status
        }

        self.checkpoints.append(checkpoint)
        self._save_checkpoints()

        try:
            from observability.metrics import record_checkpoint_built
            record_checkpoint_built(status, is_simulated)
        except ImportError:
            pass

        return checkpoint

