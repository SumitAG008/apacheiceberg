"""Block 2 — Ingress Route Mutator.

Pure mathematical function implementing Moving Target Defense (MTD) route scrambling
using HMAC-SHA256. Zero I/O, zero state, constant-time validation.
"""

import os
import hmac
import hashlib
import struct
import math
import logging
from typing import Dict

logger = logging.getLogger(__name__)

try:
    import etp_core_cpp
    HAS_CPP_CORE = True
except ImportError as err:
    HAS_CPP_CORE = False
    env = os.getenv("ENVIRONMENT", "production")
    allow_fallback = os.getenv("ETP_ALLOW_PYTHON_FALLBACK", "1") != "0"
    logger.info("Native C++ etp_core_cpp engine not present in environment='%s'. Using pure Python reference fallback.", env)
    if env == "strict_production" and not allow_fallback:
        raise RuntimeError(
            f"Native etp_core_cpp module is required in environment='{env}' when ETP_ALLOW_PYTHON_FALLBACK=0."
        ) from err


class RouteMutator:
    """Computes and validates time-scrambled ingress routes for smart meter endpoints."""

    def __init__(self, secret_key: bytes, window_s: int = 60, base_uri: str = "/api/v1/telemetry"):
        if len(secret_key) < 32:
            raise ValueError("Secret key must be at least 32 bytes (256 bits)")
        self.secret_key = secret_key
        self.window_s = window_s
        self.base_uri = base_uri.rstrip('/')

        if HAS_CPP_CORE:
            secret_str = secret_key.decode('latin1') if isinstance(secret_key, bytes) else str(secret_key)
            self._cpp_mutator = etp_core_cpp.RouteMutator(secret_str, window_s, self.base_uri)
        else:
            self._cpp_mutator = None

    def _scramble_hex(self, window: int) -> str:
        """Derives 12-char hex scramble from HMAC-SHA256 of big-endian uint64 window."""
        msg = struct.pack(">Q", window)
        digest = hmac.new(self.secret_key, msg, hashlib.sha256).hexdigest()
        return digest[:12]

    def active_routes(self, now_epoch_s: int) -> Dict[str, str]:
        """Returns the three currently valid route strings (window W-1, W, W+1)."""
        if self._cpp_mutator:
            routes = self._cpp_mutator.get_routes(now_epoch_s)
            return {
                "prev": routes.prev_route,
                "current": routes.current_route,
                "next": routes.next_route
            }

        w = math.floor(now_epoch_s / self.window_s)
        return {
            "prev": f"{self.base_uri}/rotated_{self._scramble_hex(w - 1)}",
            "current": f"{self.base_uri}/rotated_{self._scramble_hex(w)}",
            "next": f"{self.base_uri}/rotated_{self._scramble_hex(w + 1)}"
        }

    def validate_route(self, requested_path: str, now_epoch_s: int) -> bool:
        """Executes constant-time comparison against active route map to eliminate side-channels."""
        if self._cpp_mutator:
            return self._cpp_mutator.validate_route(requested_path, now_epoch_s)

        valid_map = self.active_routes(now_epoch_s)
        req_bytes = requested_path.encode('utf-8')
        
        # Check all valid routes in constant time
        matched = False
        for valid_route in valid_map.values():
            valid_bytes = valid_route.encode('utf-8')
            if hmac.compare_digest(req_bytes, valid_bytes):
                matched = True
        return matched
