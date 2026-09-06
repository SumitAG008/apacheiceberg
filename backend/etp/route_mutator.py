"""Block 2 — Ingress Route Mutator.

Pure mathematical function implementing Moving Target Defense (MTD) route scrambling
using HMAC-SHA256. Zero I/O, zero state, constant-time validation.
"""

import hmac
import hashlib
import struct
import math
from typing import Dict


class RouteMutator:
    """Computes and validates time-scrambled ingress routes for smart meter endpoints."""

    def __init__(self, secret_key: bytes, window_s: int = 60, base_uri: str = "/api/v1/telemetry"):
        if len(secret_key) < 32:
            raise ValueError("Secret key must be at least 32 bytes (256 bits)")
        self.secret_key = secret_key
        self.window_s = window_s
        self.base_uri = base_uri.rstrip('/')

    def _scramble_hex(self, window: int) -> str:
        """Derives 12-char hex scramble from HMAC-SHA256 of big-endian uint64 window."""
        msg = struct.pack(">Q", window)
        digest = hmac.new(self.secret_key, msg, hashlib.sha256).hexdigest()
        return digest[:12]

    def active_routes(self, now_epoch_s: int) -> Dict[str, str]:
        """Returns the three currently valid route strings (window W-1, W, W+1)."""
        w = math.floor(now_epoch_s / self.window_s)
        return {
            "prev": f"{self.base_uri}/rotated_{self._scramble_hex(w - 1)}",
            "current": f"{self.base_uri}/rotated_{self._scramble_hex(w)}",
            "next": f"{self.base_uri}/rotated_{self._scramble_hex(w + 1)}"
        }

    def validate_route(self, requested_path: str, now_epoch_s: int) -> bool:
        """Executes constant-time comparison against active route map to eliminate side-channels."""
        valid_map = self.active_routes(now_epoch_s)
        req_bytes = requested_path.encode('utf-8')
        
        # Check all valid routes in constant time
        matched = False
        for valid_route in valid_map.values():
            valid_bytes = valid_route.encode('utf-8')
            if hmac.compare_digest(req_bytes, valid_bytes):
                matched = True
        return matched
