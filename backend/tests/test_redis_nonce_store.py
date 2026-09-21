"""Tests for ETP Nonce Store (MemoryNonceStore & RedisNonceStore).

Includes atomic Lua script verification, multi-threaded race condition tests, and production fail-closed tests.
"""

import concurrent.futures
import os
import threading
import pytest
from etp.nonce_store import MemoryNonceStore, RedisNonceStore, AbstractNonceStore, LUA_CHECK_ONLY, LUA_COMMIT


class FakeLuaRedisClient:
    """In-memory Redis client mock supporting eval for Lua scripts and atomic lock simulation."""

    def __init__(self):
        self._data = {}
        self._lock = threading.Lock()

    def ping(self):
        return True

    def hget(self, key: str, field: str):
        with self._lock:
            hash_dict = self._data.get(key, {})
            return hash_dict.get(field)

    def eval(self, script: str, numkeys: int, key: str, *args):
        with self._lock:
            record = self._data.get(key, {})
            inc_nonce = int(args[0])

            if script == LUA_CHECK_ONLY:
                win_size = int(args[1])
                if not record or "last_nonce" not in record:
                    return [1, -1, "OK"]
                
                last_nonce = int(record["last_nonce"])
                seen_bitmap = int(record.get("seen_bitmap", 0))

                if inc_nonce > last_nonce:
                    return [1, last_nonce, "OK"]

                diff = last_nonce - inc_nonce
                if diff < win_size:
                    is_seen = (seen_bitmap >> diff) & 1
                    if is_seen == 1:
                        return [0, last_nonce, "REPLAY_REJECTED"]
                    return [1, last_nonce, "OK_BACKFILL"]
                else:
                    return [0, last_nonce, "EXPIRED_NONCE_REJECTED"]

            elif script == LUA_COMMIT:
                inc_hash = args[1]
                timestamp = args[2]
                win_size = int(args[3])
                mask = (1 << win_size) - 1

                if not record or "last_nonce" not in record:
                    self._data[key] = {
                        "last_nonce": inc_nonce,
                        "seen_bitmap": 1,
                        "last_hash": inc_hash,
                        "updated_at": timestamp
                    }
                    return [1, inc_nonce, "ACCEPT"]

                last_nonce = int(record["last_nonce"])
                seen_bitmap = int(record.get("seen_bitmap", 0))

                if inc_nonce > last_nonce:
                    shift = inc_nonce - last_nonce
                    if shift >= win_size:
                        new_bitmap = 1
                    else:
                        new_bitmap = ((seen_bitmap << shift) | 1) & mask

                    self._data[key] = {
                        "last_nonce": inc_nonce,
                        "seen_bitmap": new_bitmap,
                        "last_hash": inc_hash,
                        "updated_at": timestamp
                    }
                    return [1, inc_nonce, "ACCEPT"]

                diff = last_nonce - inc_nonce
                if diff < win_size:
                    if (seen_bitmap >> diff) & 1 == 1:
                        return [0, last_nonce, "REPLAY_REJECTED"]

                    new_bitmap = seen_bitmap | (1 << diff)
                    self._data[key]["seen_bitmap"] = new_bitmap
                    self._data[key]["updated_at"] = timestamp
                    return [1, inc_nonce, "ACCEPT_BACKFILL"]

                return [0, last_nonce, "EXPIRED_NONCE_REJECTED"]

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


def test_redis_nonce_store_with_fake_lua_redis():
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


def test_redis_nonce_store_concurrent_threads_atomic():
    """Concurrency Test: 10 worker threads attempt to commit the exact same nonce simultaneously.
    
    Verifies that server-side Lua atomicity allows EXACTLY ONE acceptance and rejects 9 replays.
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

    # In development mode, fallback is permitted
    monkeypatch.setenv("ENVIRONMENT", "development")
    dev_store = RedisNonceStore(redis_client=None, redis_url=None, window_size=32)
    assert dev_store.redis is None
