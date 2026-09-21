"""Tests for ETP Nonce Store (MemoryNonceStore & RedisNonceStore)."""

import pytest
from etp.nonce_store import MemoryNonceStore, RedisNonceStore, AbstractNonceStore


class FakeRedisClient:
    """In-memory Redis client mock for testing RedisNonceStore without an external Redis server."""

    def __init__(self):
        self._data = {}

    def ping(self):
        return True

    def hgetall(self, key: str):
        return dict(self._data.get(key, {}))

    def hget(self, key: str, field: str):
        hash_dict = self._data.get(key, {})
        return hash_dict.get(field)

    def hset(self, key: str, mapping: dict = None, **kwargs):
        if key not in self._data:
            self._data[key] = {}
        if mapping:
            self._data[key].update(mapping)
        if kwargs:
            self._data[key].update(kwargs)
        return True

    def pipeline(self):
        return self


def test_memory_nonce_store_interface():
    store = MemoryNonceStore(window_size=64)
    assert isinstance(store, AbstractNonceStore)

    # 1. New meter check
    status, last_n, msg = store.check_only("MPAN-1", 100)
    assert status == 1
    assert last_n == -1

    # 2. First commit
    c_status, c_n, c_msg = store.commit("MPAN-1", 100, "hash100", "2026-09-22T00:00:00Z")
    assert c_status == 1
    assert c_n == 100
    assert c_msg == "ACCEPT"
    assert store.get_last_hash("MPAN-1") == "hash100"

    # 3. Replay check & commit
    chk_st, last_n, msg = store.check_only("MPAN-1", 100)
    assert chk_st == 0
    assert msg == "REPLAY_REJECTED"

    rep_st, _, _ = store.commit("MPAN-1", 100, "hash100", "2026-09-22T00:00:01Z")
    assert rep_st == 0

    # 4. Sequential advancement
    seq_st, _, _ = store.commit("MPAN-1", 101, "hash101", "2026-09-22T00:01:00Z")
    assert seq_st == 1
    assert store.get_last_hash("MPAN-1") == "hash101"


def test_memory_nonce_store_backfill_and_expired():
    store = MemoryNonceStore(window_size=10)
    store.commit("MPAN-2", 100, "hash100", "2026-09-22T00:00:00Z")

    # Backfill missing nonce 95 (within window diff 5 < 10)
    bf_chk, _, _ = store.check_only("MPAN-2", 95)
    assert bf_chk == 1

    bf_comm, _, _ = store.commit("MPAN-2", 95, "hash95", "2026-09-22T00:00:01Z")
    assert bf_comm == 1
    # CRITICAL: Chain head last_hash must NOT be overwritten by backfilled older nonce!
    assert store.get_last_hash("MPAN-2") == "hash100"

    # Replay of backfilled nonce 95
    bf_rep, _, _ = store.commit("MPAN-2", 95, "hash95", "2026-09-22T00:00:02Z")
    assert bf_rep == 0

    # Expired nonce 85 (diff 15 >= window_size 10)
    exp_chk, _, msg = store.check_only("MPAN-2", 85)
    assert exp_chk == 0
    assert msg == "EXPIRED_NONCE_REJECTED"


def test_redis_nonce_store_with_fake_redis():
    fake_client = FakeRedisClient()
    redis_store = RedisNonceStore(redis_client=fake_client, window_size=64)

    # 1. Initial check & commit
    st, last_n, msg = redis_store.check_only("MPAN-REDIS-1", 50)
    assert st == 1

    c_st, c_n, c_msg = redis_store.commit("MPAN-REDIS-1", 50, "hash50", "2026-09-22T00:00:00Z")
    assert c_st == 1
    assert redis_store.get_last_hash("MPAN-REDIS-1") == "hash50"

    # 2. Replay check
    chk_st, _, msg = redis_store.check_only("MPAN-REDIS-1", 50)
    assert chk_st == 0
    assert msg == "REPLAY_REJECTED"

    # 3. Advance nonce
    adv_st, _, _ = redis_store.commit("MPAN-REDIS-1", 55, "hash55", "2026-09-22T00:05:00Z")
    assert adv_st == 1
    assert redis_store.get_last_hash("MPAN-REDIS-1") == "hash55"


def test_redis_nonce_store_fallback_when_unconnected():
    # Store initialized without Redis client defaults cleanly to in-memory store
    store = RedisNonceStore(redis_client=None, redis_url=None, window_size=32)
    st, _, _ = store.commit("MPAN-FALLBACK", 10, "h10", "2026-09-22T00:00:00Z")
    assert st == 1
    assert store.get_last_hash("MPAN-FALLBACK") == "h10"
