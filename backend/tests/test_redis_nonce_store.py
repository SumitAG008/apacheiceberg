"""Tests for ETP Nonce Store (MemoryNonceStore & RedisNonceStore).

Includes atomic Lua CAS verification, 1024-window big-integer math tests, multi-threaded concurrency tests,
and production fail-closed security tests.
"""

import concurrent.futures
import os
import threading
import pytest
from etp.nonce_store import MemoryNonceStore, RedisNonceStore, AbstractNonceStore, LUA_CAS_COMMIT


class FakeLuaRedisClient:
    """In-memory Redis client mock supporting atomic eval for LUA_CAS_COMMIT script execution."""

    def __init__(self):
        self._data = {}
        self._lock = threading.Lock()

    def ping(self):
        return True

    def hget(self, key: str, field: str):
        with self._lock:
            hash_dict = self._data.get(key, {})
            return hash_dict.get(field)

    def hgetall(self, key: str):
        with self._lock:
            return dict(self._data.get(key, {}))

    def eval(self, script: str, numkeys: int, key: str, *args):
        with self._lock:
            if script == LUA_CAS_COMMIT:
                exp_last = args[0]
                exp_seen = args[1]
                new_last = args[2]
                new_seen = args[3]
                new_hash = args[4]
                timestamp = args[5]

                record = self._data.get(key, {})
                curr_last = str(record.get("last_nonce", "-1"))
                curr_seen = str(record.get("seen_bitmap", "0"))

                if curr_last == exp_last and curr_seen == exp_seen:
                    self._data[key] = {
                        "last_nonce": new_last,
                        "seen_bitmap": new_seen,
                        "last_hash": new_hash,
                        "updated_at": timestamp
                    }
                    return 1
                else:
                    return 0

            raise ValueError("Unsupported Lua script in FakeLuaRedisClient")


def test_memory_nonce_store_interface():
    store = MemoryNonceStore(window_size=64)
    assert isinstance(store, AbstractNonceStore)

    status, last_n, msg = store.check_only("MPAN-1", 100)
    assert status == 1
    assert last_n == -1

    c_status, c_n, c_msg = store.commit("MPAN-1", 100, "hash100", "2026-09-22T00:00:00Z")
    assert c_status == 1
    assert c_n == 100
    assert c_msg == "ACCEPT"
    assert store.get_last_hash("MPAN-1") == "hash100"

    chk_st, last_n, msg = store.check_only("MPAN-1", 100)
    assert chk_st == 0
    assert msg == "REPLAY_REJECTED"

    rep_st, _, _ = store.commit("MPAN-1", 100, "hash100", "2026-09-22T00:00:01Z")
    assert rep_st == 0

    seq_st, _, _ = store.commit("MPAN-1", 101, "hash101", "2026-09-22T00:01:00Z")
    assert seq_st == 1
    assert store.get_last_hash("MPAN-1") == "hash101"


def test_memory_nonce_store_backfill_and_expired():
    store = MemoryNonceStore(window_size=10)
    store.commit("MPAN-2", 100, "hash100", "2026-09-22T00:00:00Z")

    bf_chk, _, _ = store.check_only("MPAN-2", 95)
    assert bf_chk == 1

    bf_comm, _, _ = store.commit("MPAN-2", 95, "hash95", "2026-09-22T00:00:01Z")
    assert bf_comm == 1
    assert store.get_last_hash("MPAN-2") == "hash100"

    bf_rep, _, _ = store.commit("MPAN-2", 95, "hash95", "2026-09-22T00:00:02Z")
    assert bf_rep == 0

    exp_chk, _, msg = store.check_only("MPAN-2", 85)
    assert exp_chk == 0
    assert msg == "EXPIRED_NONCE_REJECTED"


def test_redis_nonce_store_with_fake_lua_redis_cas():
    fake_client = FakeLuaRedisClient()
    redis_store = RedisNonceStore(redis_client=fake_client, window_size=64)

    st, last_n, msg = redis_store.check_only("MPAN-REDIS-1", 50)
    assert st == 1

    c_st, c_n, c_msg = redis_store.commit("MPAN-REDIS-1", 50, "hash50", "2026-09-22T00:00:00Z")
    assert c_st == 1
    assert redis_store.get_last_hash("MPAN-REDIS-1") == "hash50"

    chk_st, _, msg = redis_store.check_only("MPAN-REDIS-1", 50)
    assert chk_st == 0
    assert msg == "REPLAY_REJECTED"

    adv_st, _, _ = redis_store.commit("MPAN-REDIS-1", 55, "hash55", "2026-09-22T00:05:00Z")
    assert adv_st == 1
    assert redis_store.get_last_hash("MPAN-REDIS-1") == "hash55"


def test_redis_nonce_store_large_window_size_no_float_overflow():
    """Verifies window_size=1024 works with nonces > 100 without IEEE 754 float overflow (inf)."""
    fake_client = FakeLuaRedisClient()
    redis_store = RedisNonceStore(redis_client=fake_client, window_size=1024)

    mpan = "MPAN-LARGE-WINDOW"
    # Commit initial nonce 100
    redis_store.commit(mpan, 100, "h100", "2026-09-22T00:00:00Z")

    # Advance through 200 nonces (exceeding 53-bit double floating point precision)
    for n in range(101, 300):
        st, committed_n, msg = redis_store.commit(mpan, n, f"h{n}", f"2026-09-22T00:00:{n%60:02d}Z")
        assert st == 1
        assert committed_n == n

    # Replay of nonce 250 must be rejected
    rep_st, _, rep_msg = redis_store.commit(mpan, 250, "h250", "2026-09-22T01:00:00Z")
    assert rep_st == 0
    assert rep_msg == "REPLAY_REJECTED"

    # Out-of-order backfill of nonce 280 (not seen yet) must be accepted
    # Advance to 350 first
    redis_store.commit(mpan, 350, "h350", "2026-09-22T02:00:00Z")
    bf_st, _, _ = redis_store.commit(mpan, 340, "h340", "2026-09-22T02:05:00Z")
    assert bf_st == 1


def test_redis_nonce_store_concurrent_threads_atomic():
    """Concurrency Test: 10 worker threads attempt to commit the exact same nonce simultaneously.
    
    Verifies that Lua Compare-And-Swap (CAS) allows EXACTLY ONE acceptance and rejects 9 replays.
    """
    fake_client = FakeLuaRedisClient()
    redis_store = RedisNonceStore(redis_client=fake_client, window_size=64)
    mpan = "MPAN-RACE-CONCURRENT"
    target_nonce = 500

    accepts = 0
    rejections = 0
    lock = threading.Lock()

    def worker(worker_id: int):
        nonlocal accepts, rejections
        status, _, msg = redis_store.commit(mpan, target_nonce, f"hash_{worker_id}", "2026-09-22T00:00:00Z")
        with lock:
            if status == 1:
                accepts += 1
            else:
                rejections += 1

    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(worker, i) for i in range(10)]
        concurrent.futures.wait(futures)

    assert accepts == 1, f"Expected exactly 1 acceptance, but got {accepts}"
    assert rejections == 9, f"Expected 9 rejections, but got {rejections}"


def test_redis_nonce_store_fail_closed_in_production(monkeypatch):
    """Security Guard Test: Redis connection failure MUST raise RuntimeError in production."""
    monkeypatch.setenv("ENVIRONMENT", "production")

    with pytest.raises(RuntimeError, match="Refusing to fall back to process-local memory store"):
        RedisNonceStore(redis_client=None, redis_url="redis://invalid.host:6379/0", window_size=32)

    monkeypatch.setenv("ENVIRONMENT", "development")
    dev_store = RedisNonceStore(redis_client=None, redis_url=None, window_size=32)
    assert dev_store.redis is None
