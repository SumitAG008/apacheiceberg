"""Block 3 — ETP Ingestion Gateway.

Executes Moving Target Defense route validation, atomic nonce CAS checks (before ECDSA math
for DoS resistance), canonical hash verification, and deception proxy dispatch.
"""

import hmac
import time
import datetime
from typing import Dict, Any, Tuple, Optional
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives import hashes

from .route_mutator import RouteMutator
from .meter import TelemetryBlock, UNIT_SEPARATOR, compute_canonical_hash
from .phantom_grid import PhantomGridHoneypot
from .security import ETPSecurityManager


import threading
import warnings

class MemoryNonceStore:
    """In-memory atomic nonce store with separate non-committal check and commit operations."""

    def __init__(self):
        # mpan -> {"last_nonce": int, "last_hash": str, "updated_at": str}
        self._store: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.Lock()

    def check_only(self, mpan: str, incoming_nonce: int) -> Tuple[int, int, str]:
        """Non-committal replay check. NEVER mutates state.
        Returns: (status: 1=OK / 0=REPLAY, last_nonce: int, message: str)
        """
        record = self._store.get(mpan)
        if record is not None:
            last_nonce = record["last_nonce"]
            if incoming_nonce <= last_nonce:
                return 0, last_nonce, "REPLAY_REJECTED"
            return 1, last_nonce, "OK"
        return 1, -1, "OK"

    def commit(self, mpan: str, incoming_nonce: int, incoming_hash: str, timestamp: str) -> Tuple[int, int, str]:
        """Advance counter for a FULLY VERIFIED block under thread lock."""
        with self._lock:
            record = self._store.get(mpan)
            if record is not None and incoming_nonce <= record["last_nonce"]:
                return 0, record["last_nonce"], "REPLAY_REJECTED"
            self._store[mpan] = {
                "last_nonce": incoming_nonce,
                "last_hash": incoming_hash,
                "updated_at": timestamp,
            }
            return 1, incoming_nonce, "ACCEPT"

    def atomic_cas(self, mpan: str, incoming_nonce: int, incoming_hash: str, timestamp: str) -> Tuple[int, int, str]:
        """DEPRECATED — check-and-commit in one step."""
        warnings.warn(
            "atomic_cas() commits before verification (ETP-2026-001); "
            "use check_only() then commit()",
            DeprecationWarning,
            stacklevel=2,
        )
        status, last, msg = self.check_only(mpan, incoming_nonce)
        if status == 0:
            return status, last, msg
        return self.commit(mpan, incoming_nonce, incoming_hash, timestamp)

    def get_last_hash(self, mpan: str) -> Optional[str]:
        record = self._store.get(mpan)
        return record["last_hash"] if record else None


class ETPGateway:
    """Ingestion boundary gateway."""

    def __init__(
        self,
        route_mutator: RouteMutator,
        nonce_store: MemoryNonceStore,
        phantom_grid: PhantomGridHoneypot,
        security_manager: ETPSecurityManager = None
    ):
        self.route_mutator = route_mutator
        self.nonce_store = nonce_store
        self.phantom_grid = phantom_grid
        self.security = security_manager or ETPSecurityManager()
        self.public_key_registry: Dict[str, ec.EllipticCurvePublicKey] = {}
        self.audit_log: list = []

    def register_meter_public_key(self, mpan: str, public_key: ec.EllipticCurvePublicKey):
        """Registers a meter's public key for signature verification."""
        self.public_key_registry[mpan] = public_key

    def verify_signature(self, block: TelemetryBlock) -> bool:
        """Verifies ECDSA signature against public key registry."""
        pub_key = self.public_key_registry.get(block.mpan)
        if not pub_key:
            return False
        
        try:
            hash_bytes = bytes.fromhex(block.block_hash)
            sig_bytes = bytes.fromhex(block.signature)
            pub_key.verify(sig_bytes, hash_bytes, ec.ECDSA(hashes.SHA256()))
            return True
        except Exception:
            return False

    def process_request(
        self,
        requested_path: str,
        payload: Dict[str, Any],
        now_epoch_s: int,
        source_ip: str = "192.0.2.1"
    ) -> Tuple[int, Dict[str, Any]]:
        """Processes an incoming HTTP POST request following strict verification order."""
        
        # 1. Route Check (Constant-Time MTD Validation)
        if not self.route_mutator.validate_route(requested_path, now_epoch_s):
            # Invalid or expired route -> divert silently to Phantom Grid (UC-03)
            synthetic_response = self.phantom_grid.handle_diverted_request(
                source_ip=source_ip,
                requested_route=requested_path,
                epoch_window=now_epoch_s,
                payload=payload
            )
            self.audit_log.append({
                "action": "route.diverted",
                "source_ip": source_ip,
                "path": requested_path,
                "outcome": "DECEIVE"
            })
            return 200, synthetic_response  # Return plausible HTTP 200 OK

        # 2. Structure & Schema Validation
        try:
            block = TelemetryBlock(**payload)
        except Exception as e:
            return 400, {"status": "error", "message": f"Malformed block schema: {str(e)}"}

        # 3. Fast Nonce Check (PEEK only, zero state mutation before ECDSA verification)
        cas_status, last_nonce, cas_msg = self.nonce_store.check_only(block.mpan, block.nonce)
        if cas_status == 0:
            self.audit_log.append({
                "action": "telemetry.replay_rejected",
                "mpan": block.mpan,
                "submitted_nonce": block.nonce,
                "last_nonce": last_nonce,
                "outcome": "REPLAY_REJECTED"
            })
            return 401, {"status": "rejected", "reason": "REPLAY_REJECTED"}

        # 4. Canonical Hash Recomputation Check (using standalone module function, zero keygen cost)
        recomputed_hash = compute_canonical_hash(
            mpan=block.mpan,
            reading_kwh=block.reading_kwh,
            timestamp=block.timestamp,
            prev_hash=block.prev_hash,
            nonce=block.nonce,
            crypto_suite_id=block.crypto_suite_id,
            key_id=block.key_id
        )

        if not hmac.compare_digest(recomputed_hash, block.block_hash):
            self.audit_log.append({
                "action": "telemetry.tamper_rejected",
                "mpan": block.mpan,
                "outcome": "TAMPER_REJECTED"
            })
            return 401, {"status": "rejected", "reason": "TAMPER_REJECTED"}

        # 5. Signature Verification
        if not self.verify_signature(block):
            self.audit_log.append({
                "action": "telemetry.signature_invalid",
                "mpan": block.mpan,
                "outcome": "SIGNATURE_INVALID"
            })
            return 401, {"status": "rejected", "reason": "SIGNATURE_INVALID"}

        # 6. Chain Link Check (VERIFIED vs CHAIN_GAP)
        expected_prev_hash = self.nonce_store.get_last_hash(block.mpan)
        verify_status = "VERIFIED"
        if expected_prev_hash is not None and block.prev_hash != expected_prev_hash:
            verify_status = "CHAIN_GAP"

        # 7. State Commit (Only NOW after signature + hash verification pass!)
        commit_status, committed_last, _ = self.nonce_store.commit(
            mpan=block.mpan,
            incoming_nonce=block.nonce,
            incoming_hash=block.block_hash,
            timestamp=block.timestamp
        )
        if commit_status == 0:
            self.audit_log.append({
                "action": "telemetry.replay_rejected",
                "mpan": block.mpan,
                "submitted_nonce": block.nonce,
                "last_nonce": committed_last,
                "outcome": "REPLAY_REJECTED_ON_COMMIT",
            })
            return 401, {"status": "rejected", "reason": "REPLAY_REJECTED"}

        self.audit_log.append({
            "action": "telemetry.ingest",
            "mpan": block.mpan,
            "nonce": block.nonce,
            "verify_status": verify_status,
            "outcome": "ALLOW"
        })

        return 200, {
            "status": "accepted",
            "verify_status": verify_status,
            "block_hash": block.block_hash
        }
