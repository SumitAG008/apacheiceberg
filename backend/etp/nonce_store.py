"""Block 3b — Production ETP Nonce Store.

Provides multi-replica atomic sliding-window nonce validation and persistence using Redis Lua scripts,
with fail-closed security guards in production environments.
"""

from abc import ABC, abstractmethod
import logging
import os
import threading
from typing import Dict, Any, Tuple, Optional

logger = logging.getLogger(__name__)

LUA_CHECK_ONLY = """
local key = KEYS[1]
local inc_nonce = tonumber(ARGV[1])
local win_size = tonumber(ARGV[2])

local last_nonce = redis.call('HGET', key, 'last_nonce')
if not last_nonce then
    return {1, -1, "OK"}
end

last_nonce = tonumber(last_nonce)
local seen_bitmap = tonumber(redis.call('HGET', key, 'seen_bitmap') or '0')

if inc_nonce > last_nonce then
    return {1, last_nonce, "OK"}
end

local diff = last_nonce - inc_nonce
if diff < win_size then
    local is_seen = math.floor(seen_bitmap / (2^diff)) % 2
    if is_seen == 1 then
        return {0, last_nonce, "REPLAY_REJECTED"}
    end
    return {1, last_nonce, "OK_BACKFILL"}
else
    return {0, last_nonce, "EXPIRED_NONCE_REJECTED"}
end
"""

LUA_COMMIT = """
local key = KEYS[1]
local inc_nonce = tonumber(ARGV[1])
local inc_hash = ARGV[2]
local timestamp = ARGV[3]
local win_size = tonumber(ARGV[4])
local mask_mod = 2^win_size

local last_nonce = redis.call('HGET', key, 'last_nonce')
if not last_nonce then
    redis.call('HMSET', key, 'last_nonce', inc_nonce, 'seen_bitmap', 1, 'last_hash', inc_hash, 'updated_at', timestamp)
    return {1, inc_nonce, "ACCEPT"}
end

last_nonce = tonumber(last_nonce)
local seen_bitmap = tonumber(redis.call('HGET', key, 'seen_bitmap') or '0')

if inc_nonce > last_nonce then
    local shift = inc_nonce - last_nonce
    local new_bitmap = 1
    if shift < win_size then
        new_bitmap = ((seen_bitmap * (2^shift)) + 1) % mask_mod
    end
    redis.call('HMSET', key, 'last_nonce', inc_nonce, 'seen_bitmap', tostring(new_bitmap), 'last_hash', inc_hash, 'updated_at', timestamp)
    return {1, inc_nonce, "ACCEPT"}
end

local diff = last_nonce - inc_nonce
if diff < win_size then
    local is_seen = math.floor(seen_bitmap / (2^diff)) % 2
    if is_seen == 1 then
        return {0, last_nonce, "REPLAY_REJECTED"}
    end
    local new_bitmap = seen_bitmap + (2^diff)
    redis.call('HSET', key, 'seen_bitmap', tostring(new_bitmap))
    redis.call('HSET', key, 'updated_at', timestamp)
    return {1, inc_nonce, "ACCEPT_BACKFILL"}
end

return {0, last_nonce, "EXPIRED_NONCE_REJECTED"}
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
    """Multi-replica production Nonce Store backed by Redis and server-side Lua scripts.
    
    Executes atomic server-side Lua scripts to eliminate read-compute-write race conditions
    across multi-replica load-balanced deployments (2 to 10+ instances).
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
            key = self._key(mpan)
            res = self.redis.eval(LUA_CHECK_ONLY, 1, key, str(incoming_nonce), str(self.window_size))
            return int(res[0]), int(res[1]), str(res[2])
        except Exception as err:
            self._assert_or_fallback("check_only", err)
            return self.fallback_store.check_only(mpan, incoming_nonce)

    def commit(self, mpan: str, incoming_nonce: int, incoming_hash: str, timestamp: str) -> Tuple[int, int, str]:
        if self.redis is None:
            self._assert_or_fallback("connection", RuntimeError("No Redis client available"))
            return self.fallback_store.commit(mpan, incoming_nonce, incoming_hash, timestamp)

        try:
            key = self._key(mpan)
            res = self.redis.eval(LUA_COMMIT, 1, key, str(incoming_nonce), incoming_hash, timestamp, str(self.window_size))
            return int(res[0]), int(res[1]), str(res[2])
        except Exception as err:
            self._assert_or_fallback("commit", err)
            return self.fallback_store.commit(mpan, incoming_nonce, incoming_hash, timestamp)

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
