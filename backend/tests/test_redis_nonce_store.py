"""Tests for ETP Nonce Store (MemoryNonceStore & RedisNonceStore).

Tests real Redis 7 Lua Compare-And-Swap (CAS) execution, multi-process cross-replica race conditions,
1024-window big-integer math, and production fail-closed security guards.
"""

import concurrent.futures
import os
import multiprocessing
import pytest
from etp.nonce_store import MemoryNonceStore, RedisNonceStore, AbstractNonceStore, LUA_CAS_COMMIT

try:
    import redis as redis_lib
    HAS_REDIS_LIB = True
except ImportError:
    HAS_REDIS_LIB = False


@pytest.fixture
def real_redis_client():
    """Fixture providing real Redis client connection gated on CI environment variable."""
    if not HAS_REDIS_LIB:
        if os.environ.get("CI") or os.environ.get("GITHUB_ACTIONS"):
            pytest.fail("redis package is missing in CI environment")
        pytest.skip("redis python package not installed")

    url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
    client = redis_lib.Redis.from_url(url, decode_responses=True)
    try:
        client.ping()
    except Exception as err:
        if os.environ.get("CI") or os.environ.get("GITHUB_ACTIONS"):
            pytest.fail(f"Redis service container unavailable in CI environment: {err}")
        pytest.skip(f"No Redis service running locally at {url}")

    # Clean test namespace before test run
    keys = client.keys("etp:meter:test:*")
    if keys:
        client.delete(*keys)
    return client


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


def test_real_redis_nonce_store_lua_cas_execution(real_redis_client):
    """Executes Option B Python big-integer + LUA_CAS_COMMIT against real Redis 7 instance."""
    prefix = "etp:meter:test:lua:"
    store = RedisNonceStore(redis_client=real_redis_client, window_size=64, prefix=prefix)
    mpan = "MPAN-REAL-REDIS-1"

    # 1. Initial check & commit
    st, last_n, msg = store.check_only(mpan, 50)
    assert st == 1

    c_st, c_n, c_msg = store.commit(mpan, 50, "hash50", "2026-09-22T00:00:00Z")
    assert c_st == 1
    assert store.get_last_hash(mpan) == "hash50"

    # 2. Replay check against real Redis state
    chk_st, _, msg = store.check_only(mpan, 50)
    assert chk_st == 0
    assert msg == "REPLAY_REJECTED"

    # 3. Advance nonce
    adv_st, _, _ = store.commit(mpan, 55, "hash55", "2026-09-22T00:05:00Z")
    assert adv_st == 1
    assert store.get_last_hash(mpan) == "hash55"


def test_real_redis_large_window_size_1024_real_roundtrip(real_redis_client):
    """Verifies 1024-bit window size survives real Redis string storage without float overflow."""
    prefix = "etp:meter:test:bigwin:"
    store = RedisNonceStore(redis_client=real_redis_client, window_size=1024, prefix=prefix)
    mpan = "MPAN-REAL-BIGWIN"

    # Commit initial nonce 100
    store.commit(mpan, 100, "h100", "2026-09-22T00:00:00Z")

    # Advance through 200 nonces (exceeding 53-bit IEEE float limit)
    for n in range(101, 300):
        st, committed_n, msg = store.commit(mpan, n, f"h{n}", f"2026-09-22T00:00:{n%60:02d}Z")
        assert st == 1
        assert committed_n == n

    # Replay of nonce 250 must be rejected
    rep_st, _, rep_msg = store.commit(mpan, 250, "h250", "2026-09-22T01:00:00Z")
    assert rep_st == 0
    assert rep_msg == "REPLAY_REJECTED"


def _process_worker_commit(redis_url: str, mpan: str, target_nonce: int, worker_id: int):
    """Worker function executed in separate OS process with its own Redis connection."""
    import redis
    client = redis.Redis.from_url(redis_url, decode_responses=True)
    store = RedisNonceStore(redis_client=client, window_size=64, prefix="etp:meter:test:proc:")
    status, _, msg = store.commit(mpan, target_nonce, f"hash_proc_{worker_id}", "2026-09-22T00:00:00Z")
    return status, msg


def test_real_redis_multiprocess_cross_replica_race(real_redis_client):
    """Multi-Process Cross-Replica Concurrency Test.
    
    Spawns 8 separate OS processes (simulating 8 load-balanced pod replicas), each with its own
    connection to real Redis 7, attempting to commit the exact same nonce for the same MPAN.
    Verifies that atomic Lua CAS allows EXACTLY ONE acceptance and 7 rejections.
    """
    url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
    mpan = "MPAN-MULTIPROC-RACE"
    target_nonce = 777

    ctx = multiprocessing.get_context("spawn")
    with concurrent.futures.ProcessPoolExecutor(max_workers=8, mp_context=ctx) as executor:
        futures = [
            executor.submit(_process_worker_commit, url, mpan, target_nonce, i)
            for i in range(8)
        ]
        results = [f.result() for f in concurrent.futures.as_completed(futures)]

    accepts = sum(1 for status, _ in results if status == 1)
    rejections = sum(1 for status, _ in results if status == 0)

    assert accepts == 1, f"Expected exactly 1 process acceptance across replicas, but got {accepts}"
    assert rejections == 7, f"Expected 7 process rejections across replicas, but got {rejections}"


def test_redis_nonce_store_fail_closed_in_production(monkeypatch):
    """Security Guard Test: Redis connection failure MUST raise RuntimeError in production."""
    monkeypatch.setenv("ENVIRONMENT", "production")

    with pytest.raises(RuntimeError, match="Refusing to fall back to process-local memory store"):
        RedisNonceStore(redis_client=None, redis_url="redis://invalid.host:6379/0", window_size=32)

    monkeypatch.setenv("ENVIRONMENT", "development")
    dev_store = RedisNonceStore(redis_client=None, redis_url=None, window_size=32)
    assert dev_store.redis is None
