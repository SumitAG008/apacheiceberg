# Copyright (c) 2026 Meldra AI Ltd. All rights reserved.
"""
observability/metrics.py — Prometheus metrics counters & latency histograms.

Provides Prometheus metrics for telemetry verification status, rejection reasons,
gateway latency, and deception honeypot events.
"""

from __future__ import annotations

import time
import logging
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

try:
    from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST
    PROMETHEUS_AVAILABLE = True
except ImportError:
    PROMETHEUS_AVAILABLE = False
    logger.warning("prometheus_client module not installed; fallback metrics recorder in use.")

if PROMETHEUS_AVAILABLE:
    VERIFICATION_COUNTER = Counter(
        "etp_verification_total",
        "Total ETP telemetry verification checks",
        ["status", "reason"]
    )
    VERIFICATION_LATENCY = Histogram(
        "etp_verification_latency_seconds",
        "ETP telemetry block verification latency in seconds",
        buckets=(0.0001, 0.0005, 0.001, 0.005, 0.01, 0.05, 0.1, 0.5, 1.0)
    )
    HONEYPOT_DIVERT_COUNTER = Counter(
        "etp_threat_honeypot_diverts_total",
        "Total unauthenticated probes diverted to Phantom Grid honeypot",
        ["route", "source_ip"]
    )
    CHECKPOINT_COUNTER = Counter(
        "etp_checkpoints_total",
        "Total Merkle tree daily checkpoints built and persisted",
        ["status", "is_simulated"]
    )
else:
    VERIFICATION_COUNTER = None
    VERIFICATION_LATENCY = None
    HONEYPOT_DIVERT_COUNTER = None
    CHECKPOINT_COUNTER = None


def record_verification(status: str, reason: str = "OK", latency_s: float = 0.0) -> None:
    """Record verification status metric and latency histogram."""
    if PROMETHEUS_AVAILABLE:
        VERIFICATION_COUNTER.labels(status=status, reason=reason).inc()
        if latency_s > 0:
            VERIFICATION_LATENCY.observe(latency_s)


def record_honeypot_divert(route: str, source_ip: str) -> None:
    """Record honeypot diversion metric."""
    if PROMETHEUS_AVAILABLE:
        HONEYPOT_DIVERT_COUNTER.labels(route=route[:50], source_ip=source_ip).inc()


def record_checkpoint_built(status: str, is_simulated: bool) -> None:
    """Record checkpoint creation metric."""
    if PROMETHEUS_AVAILABLE:
        CHECKPOINT_COUNTER.labels(status=status, is_simulated=str(is_simulated)).inc()


def get_metrics_response() -> tuple[bytes, str]:
    """Returns raw Prometheus metrics bytes and content type header."""
    if PROMETHEUS_AVAILABLE:
        return generate_latest(), CONTENT_TYPE_LATEST
    return b"# Prometheus client not installed\n", "text/plain; version=0.0.4"
