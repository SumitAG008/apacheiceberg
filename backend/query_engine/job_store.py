# Copyright (c) 2025 Meldra AI Ltd. All rights reserved.
"""
query_engine/job_store.py — Thread-safe in-memory job registry with TTL.

Stores QueryJob objects keyed by job_id. Jobs expire after TTL_SECONDS.
Ready to be swapped for a Redis-backed store without API changes.
"""

from __future__ import annotations

import asyncio
import logging
import time
from threading import Lock
from typing import Dict, List, Optional

from query_engine.models import QueryJob, QueryStatus

logger = logging.getLogger(__name__)

TTL_SECONDS = 3600        # Jobs kept for 1 hour
MAX_JOBS_PER_USER = 200   # Prevent unbounded memory growth


class JobStore:
    """
    Thread-safe in-memory store for QueryJob objects.

    Usage:
        store = JobStore()
        job = store.create(job)
        store.update(job)
        job = store.get(job_id)
        jobs = store.list_for_user(user_id, limit=20)
    """

    def __init__(self) -> None:
        self._jobs: Dict[str, QueryJob] = {}
        self._timestamps: Dict[str, float] = {}   # job_id → creation epoch
        self._lock = Lock()

    # ─── Public API ──────────────────────────────────────────────────────────

    def create(self, job: QueryJob) -> QueryJob:
        """Register a new job and return it."""
        with self._lock:
            self._prune()
            self._jobs[job.job_id] = job
            self._timestamps[job.job_id] = time.time()
            logger.debug("[JobStore] Created job %s mode=%s", job.job_id, job.mode)
        return job

    def get(self, job_id: str) -> Optional[QueryJob]:
        """Retrieve a job by ID, or None if not found / expired."""
        with self._lock:
            self._prune()
            return self._jobs.get(job_id)

    def update(self, job: QueryJob) -> None:
        """Persist an updated job (e.g. after status change)."""
        with self._lock:
            if job.job_id in self._jobs:
                self._jobs[job.job_id] = job
            else:
                # Job expired during execution; re-insert with original timestamp
                self._jobs[job.job_id] = job
                self._timestamps[job.job_id] = time.time()

    def list_for_user(
        self,
        user_id: str,
        limit: int = 50,
        status_filter: Optional[QueryStatus] = None,
    ) -> List[QueryJob]:
        """Return recent jobs submitted by a specific user, newest first."""
        with self._lock:
            self._prune()
            jobs = [
                j for j in self._jobs.values()
                if j.submitted_by == user_id
                and (status_filter is None or j.status == status_filter)
            ]
        jobs.sort(key=lambda j: j.created_at, reverse=True)
        return jobs[:limit]

    def list_all(self, limit: int = 100) -> List[QueryJob]:
        """Admin: return all recent jobs (Admin role check done at endpoint level)."""
        with self._lock:
            self._prune()
            jobs = list(self._jobs.values())
        jobs.sort(key=lambda j: j.created_at, reverse=True)
        return jobs[:limit]

    def delete(self, job_id: str) -> bool:
        """Manually remove a job. Returns True if it existed."""
        with self._lock:
            existed = job_id in self._jobs
            self._jobs.pop(job_id, None)
            self._timestamps.pop(job_id, None)
        return existed

    def stats(self) -> dict:
        """Return store statistics for health endpoints."""
        with self._lock:
            total = len(self._jobs)
            by_status: Dict[str, int] = {}
            for j in self._jobs.values():
                by_status[j.status] = by_status.get(j.status, 0) + 1
        return {"total_jobs": total, "by_status": by_status, "ttl_seconds": TTL_SECONDS}

    # ─── Internal ─────────────────────────────────────────────────────────────

    def _prune(self) -> None:
        """Remove jobs older than TTL_SECONDS. Must be called under self._lock."""
        cutoff = time.time() - TTL_SECONDS
        expired = [jid for jid, ts in self._timestamps.items() if ts < cutoff]
        for jid in expired:
            self._jobs.pop(jid, None)
            self._timestamps.pop(jid, None)
        if expired:
            logger.debug("[JobStore] Pruned %d expired jobs", len(expired))


# ─── Module-level singleton ───────────────────────────────────────────────────
# Imported and shared by the FastAPI application and the QueryEngine.

job_store = JobStore()
