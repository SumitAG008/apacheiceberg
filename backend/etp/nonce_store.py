"""Block 3b — Production ETP Nonce Store.

Provides multi-replica atomic sliding-window nonce validation and persistence using Python
arbitrary-precision big-integers paired with server-side Redis Lua Compare-And-Swap (CAS),
eliminating floating-point precision overflow while guaranteeing multi-replica atomicity.
"""

from abc import ABC, abstractmethod
import logging
import os
import threading
from typing import Dict, Any, Tuple, Optional

logger = logging.getLogger(__name__)

# Atomic Compare-And-Swap (CAS) Lua Script
LUA_CAS_COMMIT = """
local key = KEYS[1]
local exp_last = ARGV[1]
local exp_seen = ARGV[2]
local new_last = ARGV[3]
local new_seen = ARGV[4]
local new_hash = ARGV[5]
local timestamp = ARGV[6]

local curr_last = redis.call('HGET', key, 'last_nonce') or "-1"
local curr_seen = redis.call('HGET', key, 'seen_bitmap') or "0"

if curr_last == exp_last and curr_seen == exp_seen then
    redis.call('HMSET', key, 'last_nonce', new_last, 'seen_bitmap', new_seen, 'last_hash', new_hash, 'updated_at', timestamp)
    return 1
else
    return 0
end
"""


class AbstractNonceStore(ABC):
    """Abstract interface for ETP nonce validation and state persistence."""

    @abstractmethod
    def check_only(self, mpan: str, incoming_nonce: int) -> Tuple[int, int, str]:
        """Non-committal replay check using sliding window bitmap. NEVER mutates state."""
        pass

    @abstractmethod
    def commit(self, mpan: str, incoming_nonce: int, incoming_hash: str, timestamp: str) -> Tuple[int, int, str]:
        """Advance counter or set bit in sliding window for a VERIFIED block under atomic lock/transaction."""
        pass

    @abstractmethod
    def get_last_hash(self, mpan: str) -> Optional[str]:
        """Fetch current chain head hash for a meter."""
        pass


class MemoryNonceStore(AbstractNonceStore):
    """Atomic sliding-window nonce store implementing IPsec RFC 6479 anti-replay design in memory.
    
    Thread-safe for single-process workers.
    """

    def __init__(self, window_size: int = 1024):
        if window_size < 1:
            raise ValueError("window_size must be >= 1")
        self.window_size = window_size
        self.mask = (1 << window_size) - 1
        self._store: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.Lock()

    def check_only(self, mpan: str, incoming_nonce: int) -> Tuple[int, int, str]:
        with self._lock:
            record = self._store.get(mpan)
            if record is None:
                return 1, -1, "OK"
            
            last_nonce = record["last_nonce"]
            seen_bitmap = record["seen_bitmap"]
            
            if incoming_nonce > last_nonce:
                return 1, last_nonce, "OK"
            
            diff = last_nonce - incoming_nonce
            if diff < self.window_size:
                is_seen = (seen_bitmap >> diff) & 1
                if is_seen == 1:
                    return 0, last_nonce, "REPLAY_REJECTED"
                return 1, last_nonce, "OK_BACKFILL"
            else:
                return 0, last_nonce, "EXPIRED_NONCE_REJECTED"

    def commit(self, mpan: str, incoming_nonce: int, incoming_hash: str, timestamp: str) -> Tuple[int, int, str]:
        with self._lock:
            record = self._store.get(mpan)
            if record is None:
                self._store[mpan] = {
                    "last_nonce": incoming_nonce,
                    "seen_bitmap": 1,
                    "last_hash": incoming_hash,
                    "updated_at": timestamp
                }
                return 1, incoming_nonce, "ACCEPT"
            
            last_nonce = record["last_nonce"]
            seen_bitmap = record["seen_bitmap"]
            
            if incoming_nonce > last_nonce:
                shift = incoming_nonce - last_nonce
                if shift >= self.window_size:
                    new_bitmap = 1
                else:
                    new_bitmap = ((seen_bitmap << shift) | 1) & self.mask
                
                self._store[mpan] = {
                    "last_nonce": incoming_nonce,
                    "seen_bitmap": new_bitmap,
                    "last_hash": incoming_hash,
                    "updated_at": timestamp
                }
                return 1, incoming_nonce, "ACCEPT"
            
            diff = last_nonce - incoming_nonce
            if diff < self.window_size:
                if (seen_bitmap >> diff) & 1 == 1:
                    return 0, last_nonce, "REPLAY_REJECTED"
                
                new_bitmap = seen_bitmap | (1 << diff)
                self._store[mpan]["seen_bitmap"] = new_bitmap
                self._store[mpan]["updated_at"] = timestamp
                return 1, incoming_nonce, "ACCEPT_BACKFILL"
            
            return 0, last_nonce, "EXPIRED_NONCE_REJECTED"

    def get_last_hash(self, mpan: str) -> Optional[str]:
        with self._lock:
            record = self._store.get(mpan)
            return record["last_hash"] if record else None


# Backward compatibility alias
SlidingWindowNonceStore = MemoryNonceStore


class RedisNonceStore(AbstractNonceStore):
    """Multi-replica production Nonce Store backed by Redis optimistic Compare-And-Swap (CAS) Lua scripts.
    
    Uses Python arbitrary-precision big-integers for window bitwise math paired with atomic server-side Lua CAS,
    preventing both double precision truncation (`inf` at >53 nonces) and multi-replica race conditions.
    Refuses fallback in non-development environments to prevent silent fail-open security bypass.
    """

    def __init__(self, redis_client=None, redis_url: Optional[str] = None, window_size: int = 1024, prefix: str = "etp:meter:"):
        self.window_size = window_size
        self.prefix = prefix
        self.fallback_store = MemoryNonceStore(window_size=window_size)
        self.redis = redis_client

        if self.redis is None and redis_url:
            try:
                import redis
                self.redis = redis.Redis.from_url(redis_url, decode_responses=True)
                self.redis.ping()
                logger.info("Connected to Redis Nonce Store at %s", redis_url)
            except Exception as err:
                env = os.environ.get("ENVIRONMENT", "development").strip().lower()
                if env in ("development", "dev", "local", "test"):
                    logger.warning("Failed connecting to Redis (%s) — falling back to MemoryNonceStore in %s", err, env)
                    self.redis = None
                else:
                    raise RuntimeError(
                        f"Redis Nonce Store connection failed in environment '{env}': {err}. "
                        "Refusing to fall back to process-local memory store in non-development environment."
                    ) from err

    def _key(self, mpan: str) -> str:
        return f"{self.prefix}{mpan}"

    def _assert_or_fallback(self, action_name: str, err: Exception):
        env = os.environ.get("ENVIRONMENT", "development").strip().lower()
        if env in ("development", "dev", "local", "test"):
            logger.warning("Redis %s failed (%s) — falling back to MemoryNonceStore in %s", action_name, err, env)
        else:
            raise RuntimeError(
                f"Redis Nonce Store {action_name} error in environment '{env}': {err}. "
                "Refusing in-memory fallback in non-development environment to preserve replay protection."
            ) from err

    def check_only(self, mpan: str, incoming_nonce: int) -> Tuple[int, int, str]:
        if self.redis is None:
            self._assert_or_fallback("connection", RuntimeError("No Redis client available"))
            return self.fallback_store.check_only(mpan, incoming_nonce)

        try:
            data = self.redis.hgetall(self._key(mpan))
            if not data:
                return 1, -1, "OK"

            last_nonce = int(data.get("last_nonce", -1))
            seen_bitmap = int(data.get("seen_bitmap", 0))

            if incoming_nonce > last_nonce:
                return 1, last_nonce, "OK"

            diff = last_nonce - incoming_nonce
            if diff < self.window_size:
                if (seen_bitmap >> diff) & 1 == 1:
                    return 0, last_nonce, "REPLAY_REJECTED"
                return 1, last_nonce, "OK_BACKFILL"
            else:
                return 0, last_nonce, "EXPIRED_NONCE_REJECTED"
        except Exception as err:
            self._assert_or_fallback("check_only", err)
            return self.fallback_store.check_only(mpan, incoming_nonce)

    def commit(self, mpan: str, incoming_nonce: int, incoming_hash: str, timestamp: str, max_retries: int = 5) -> Tuple[int, int, str]:
        if self.redis is None:
            self._assert_or_fallback("connection", RuntimeError("No Redis client available"))
            return self.fallback_store.commit(mpan, incoming_nonce, incoming_hash, timestamp)

        key = self._key(mpan)
        mask = (1 << self.window_size) - 1

        for _ in range(max_retries):
            try:
                data = self.redis.hgetall(key)
                if not data:
                    exp_last_str = "-1"
                    exp_seen_str = "0"
                    last_nonce = None
                    seen_bitmap = 0
                else:
                    exp_last_str = str(data.get("last_nonce", "-1"))
                    exp_seen_str = str(data.get("seen_bitmap", "0"))
                    last_nonce = int(exp_last_str)
                    seen_bitmap = int(exp_seen_str)

                if last_nonce is None:
                    new_last = incoming_nonce
                    new_seen = 1
                    new_hash = incoming_hash
                    res = self.redis.eval(LUA_CAS_COMMIT, 1, key, exp_last_str, exp_seen_str, str(new_last), str(new_seen), new_hash, timestamp)
                    if int(res) == 1:
                        return 1, incoming_nonce, "ACCEPT"
                    continue

                if incoming_nonce > last_nonce:
                    shift = incoming_nonce - last_nonce
                    if shift >= self.window_size:
                        new_seen = 1
                    else:
                        new_seen = ((seen_bitmap << shift) | 1) & mask
                    new_last = incoming_nonce
                    new_hash = incoming_hash
                    res = self.redis.eval(LUA_CAS_COMMIT, 1, key, exp_last_str, exp_seen_str, str(new_last), str(new_seen), new_hash, timestamp)
                    if int(res) == 1:
                        return 1, incoming_nonce, "ACCEPT"
                    continue

                diff = last_nonce - incoming_nonce
                if diff < self.window_size:
                    if (seen_bitmap >> diff) & 1 == 1:
                        return 0, last_nonce, "REPLAY_REJECTED"

                    new_seen = seen_bitmap | (1 << diff)
                    new_last = last_nonce
                    new_hash = str(data.get("last_hash", incoming_hash))
                    res = self.redis.eval(LUA_CAS_COMMIT, 1, key, exp_last_str, exp_seen_str, str(new_last), str(new_seen), new_hash, timestamp)
                    if int(res) == 1:
                        return 1, incoming_nonce, "ACCEPT_BACKFILL"
                    continue

                return 0, last_nonce, "EXPIRED_NONCE_REJECTED"

            except Exception as err:
                self._assert_or_fallback("commit", err)
                return self.fallback_store.commit(mpan, incoming_nonce, incoming_hash, timestamp)

        return self.check_only(mpan, incoming_nonce)

    def get_last_hash(self, mpan: str) -> Optional[str]:
        if self.redis is None:
            self._assert_or_fallback("connection", RuntimeError("No Redis client available"))
            return self.fallback_store.get_last_hash(mpan)

        try:
            val = self.redis.hget(self._key(mpan), "last_hash")
            return str(val) if val is not None else None
        except Exception as err:
            self._assert_or_fallback("get_last_hash", err)
            return self.fallback_store.get_last_hash(mpan)
