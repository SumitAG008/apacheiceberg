"""Block 5 — Micro-Batch Lakehouse Writer.

Buffers verified blocks in memory and appends to Apache Iceberg tables in micro-batches
(flush every 30s or 50,000 blocks) to prevent small-file performance issues.
"""

import time
import datetime
from typing import List, Dict, Any, Tuple
from .meter import TelemetryBlock


class MicroBatchWriter:
    """Micro-batch writer converting telemetry blocks into Iceberg rows."""

    def __init__(self, flush_interval_s: float = 30.0, max_batch_size: int = 50000):
        self.flush_interval_s = flush_interval_s
        self.max_batch_size = max_batch_size
        self.buffer: List[Tuple[TelemetryBlock, str]] = []
        self.last_flush_time = time.time()
        self.committed_batches: List[List[Dict[str, Any]]] = []

    def add_block(self, block: TelemetryBlock, verify_status: str = "VERIFIED"):
        """Buffers a verified block for micro-batch write."""
        self.buffer.append((block, verify_status))
        
        # Check size threshold
        if len(self.buffer) >= self.max_batch_size:
            self.flush()

    def should_flush(self, now_s: float = None) -> bool:
        """Checks if flush time interval or batch size threshold is reached."""
        if now_s is None:
            now_s = time.time()
        return (len(self.buffer) >= self.max_batch_size) or ((now_s - self.last_flush_time) >= self.flush_interval_s)

    def flush(self) -> List[Dict[str, Any]]:
        """Flushes in-memory buffer to Iceberg rows."""
        if not self.buffer:
            return []

        rows: List[Dict[str, Any]] = []
        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()

        for block, status in self.buffer:
            # Calculate settlement period (1..48 half-hourly)
            dt = datetime.datetime.fromisoformat(block.timestamp.replace('Z', '+00:00'))
            settlement_period = (dt.hour * 2) + (1 if dt.minute < 30 else 2)

            row = {
                "mpan": block.mpan,
                "reading_ts": block.timestamp,
                "settlement_period": settlement_period,
                "reading_kwh": block.reading_kwh,
                "voltage_v": 230.0,  # Nominal RMS voltage
                "feeder_id": "F-4471",
                "substation_id": "SUB-0912",
                "gsp_group": "_A",
                "etp_block_hash": block.block_hash,
                "etp_prev_hash": block.prev_hash,
                "etp_nonce": block.nonce,
                "etp_key_id": block.key_id,
                "etp_crypto_suite_id": block.crypto_suite_id,
                "etp_signature": block.signature,
                "etp_verified_at": now_iso,
                "etp_verify_status": status,
                "etp_sentinel_score": 0.0,
                "etp_gateway_id": "gw-uk-01",
                "ingested_at": now_iso,
                "source_batch_id": f"batch_{int(self.last_flush_time)}"
            }
            rows.append(row)

        self.committed_batches.append(rows)
        self.buffer.clear()
        self.last_flush_time = time.time()
        return rows
