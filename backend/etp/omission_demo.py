"""60-Second Smart Meter Telemetry Omission & Dispute Demonstration Module.

Simulates a 24-hour half-hourly smart meter telemetry stream (48 readings), simulates 
comms loss by dropping 6 readings, and generates a cryptographically authenticated
Merkle checkpoint with RFC 3161 TSA timestamp anchoring flagging ANCHORED_WITH_GAPS.
"""

import datetime
import hashlib
import json
import logging
from typing import Dict, Any, List, Optional, Tuple

from .meter import compute_canonical_hash
from .checkpointer import MerkleCheckpointer, create_rfc3161_anchor_token

logger = logging.getLogger(__name__)


def generate_synthetic_daily_telemetry(
    mpan: str = "MPAN-1200098765432",
    day_iso: str = "2026-09-22",
    start_nonce: int = 1001,
    drop_indices: Optional[List[int]] = None
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Generates synthetic half-hourly smart meter readings for a 24-hour day (48 readings).
    
    Args:
        mpan: Meter Point Administration Number.
        day_iso: Date string (YYYY-MM-DD).
        start_nonce: Initial monotonic nonce counter.
        drop_indices: 0-indexed reading positions to omit (simulating network loss).
        
    Returns:
        Tuple of (submitted_readings, all_generated_readings)
    """
    drop_set = set(drop_indices or [])
    all_readings = []
    submitted_readings = []

    base_time = datetime.datetime.fromisoformat(f"{day_iso}T00:00:00.000Z")
    prev_hash = "0" * 64

    for i in range(48):
        current_time = base_time + datetime.timedelta(minutes=30 * i)
        ts_str = current_time.strftime("%Y-%m-%dT%H:%M:%S.000Z")
        nonce = start_nonce + i

        # Synthetic kWh reading with realistic diurnal load pattern
        reading_kwh = round(0.15 + (i % 8) * 0.05, 3)

        block_hash = compute_canonical_hash(
            mpan=mpan,
            reading_kwh=reading_kwh,
            timestamp=ts_str,
            prev_hash=prev_hash,
            nonce=nonce,
            crypto_suite_id="ECDSA-P256-SHA256-v1",
            key_id="k-meter-demo"
        )

        reading = {
            "mpan": mpan,
            "reading_kwh": reading_kwh,
            "timestamp": ts_str,
            "prev_hash": prev_hash,
            "etp_nonce": nonce,
            "etp_block_hash": block_hash
        }

        all_readings.append(reading)
        if i not in drop_set:
            submitted_readings.append(reading)

        prev_hash = block_hash

    return submitted_readings, all_readings


def run_60s_omission_demo(
    tsa_url: Optional[str] = "http://freetsa.org/tsr",
    mpan: str = "MPAN-1200098765432",
    day: str = "2026-09-22"
) -> Dict[str, Any]:
    """Executes the 60-second telemetry omission detection demo.
    
    Returns a structured demo report containing Merkle root, gap count, and RFC 3161 TSA token.
    """
    logger.info("Starting 60-Second Telemetry Omission & Dispute Demo for meter %s...", mpan)

    # 1. Generate 48 readings, drop 6 (readings #24 through #29 simulating 3-hour grid outage)
    dropped_positions = [24, 25, 26, 27, 28, 29]
    submitted_readings, all_readings = generate_synthetic_daily_telemetry(
        mpan=mpan,
        day_iso=day,
        start_nonce=1001,
        drop_indices=dropped_positions
    )

    # 2. Build Merkle tree checkpoint with expected_daily_readings=48
    checkpointer = MerkleCheckpointer(tsa_url=tsa_url, storage_path="backend/data/demo_checkpoints.json")
    checkpoint = checkpointer.build_meter_day_checkpoint(
        mpan=mpan,
        day=day,
        readings=submitted_readings,
        prev_day_last_nonce=1000,
        expected_daily_readings=48
    )

    # 3. Format presentation report
    report = {
        "title": "ETP 60-Second Telemetry Omission & Dispute Demonstration",
        "meter_id": mpan,
        "date": day,
        "expected_readings": 48,
        "received_readings": len(submitted_readings),
        "omitted_readings_count": checkpoint["gap_count"],
        "omitted_time_window": "12:00 UTC to 15:00 UTC (3-Hour Outage Window)",
        "checkpoint_status": checkpoint["status"],
        "merkle_root": checkpoint["merkle_root"],
        "authenticated_anchor_digest": checkpoint["anchor_digest"],
        "tsa_anchor_ref": checkpoint["anchor_ref"],
        "is_simulated_tsa": checkpoint["is_simulated_anchor"],
        "built_at_utc": checkpoint["built_at"],
        "dispute_verdict": "OMISSION_DETECTED_AND_PROVEN" if checkpoint["status"] == "ANCHORED_WITH_GAPS" else "COMPLETE"
    }

    return report


if __name__ == "__main__":
    demo_result = run_60s_omission_demo()
    print(json.dumps(demo_result, indent=2))
