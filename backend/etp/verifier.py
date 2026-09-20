"""Block 7 — Provenance Verification Engine.

Validates analytical SQL query results against anchored Merkle tree checkpoints and emits
Verification-Aware Query Objects (Figure + Snapshot ID + SQL String + Merkle Proof).
"""

import datetime
from dataclasses import dataclass, asdict
from typing import List, Dict, Any, Optional
from .checkpointer import MerkleCheckpointer, canonical_merkle_root


@dataclass(frozen=True)
class VerificationReport:
    """Detailed verification audit report for a meter-day range."""
    mpan: str
    day_range: str
    rows_checked: int
    verified_count: int
    failed_count: int
    chain_gap_count: int
    merkle_root: str
    anchor_ref: str
    status: str  # VERIFIED | VERIFIED_WITH_GAPS | FAILED | UNANCHORED

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class VerificationAwareQueryObject:
    """Unified query response object combining calculation results with provenance proofs."""
    query_id: str
    executed_at: str
    snapshot_id: int
    sql_string: str
    result_set: List[Dict[str, Any]]
    verification_proof: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class ETPVerifier:
    """Verification engine checking Iceberg table partitions against anchored Merkle roots."""

    def __init__(self, checkpointer: MerkleCheckpointer):
        self.checkpointer = checkpointer

    def verify_meter_day_readings(
        self,
        mpan: str,
        day: str,
        readings: List[Dict[str, Any]]
    ) -> VerificationReport:
        """Verifies a set of readings against anchored checkpoints."""
        if not readings:
            return VerificationReport(
                mpan=mpan,
                day_range=day,
                rows_checked=0,
                verified_count=0,
                failed_count=0,
                chain_gap_count=0,
                merkle_root="",
                anchor_ref="",
                status="UNANCHORED"
            )

        # 1. Count verification statuses
        verified = 0
        failed = 0
        gaps = 0

        for r in readings:
            status = r.get("etp_verify_status", "UNVERIFIED")
            if status == "VERIFIED":
                verified += 1
            elif status == "CHAIN_GAP":
                gaps += 1
            else:
                failed += 1

        # 2. Recompute Merkle root over block hashes
        sorted_readings = sorted(readings, key=lambda x: x.get("etp_nonce", 0))
        hashes = [r["etp_block_hash"] for r in sorted_readings]
        computed_root = canonical_merkle_root(hashes)

        # 3. Find matching anchored checkpoint & compare Merkle root
        anchor_ref = ""
        checkpoint_match = None
        for cp in reversed(self.checkpointer.checkpoints):
            if cp["mpan"] == mpan and cp["day"] == day:
                checkpoint_match = cp
                anchor_ref = cp.get("anchor_ref", "")
                break

        overall_status = "VERIFIED"
        if not checkpoint_match:
            overall_status = "UNANCHORED"
        elif checkpoint_match.get("merkle_root") != computed_root:
            overall_status = "FAILED"
            failed = len(readings)
            verified = 0
        elif failed > 0:
            overall_status = "FAILED"
        elif gaps > 0:
            overall_status = "VERIFIED_WITH_GAPS"

        return VerificationReport(
            mpan=mpan,
            day_range=day,
            rows_checked=len(readings),
            verified_count=verified,
            failed_count=failed,
            chain_gap_count=gaps,
            merkle_root=computed_root,
            anchor_ref=anchor_ref,
            status=overall_status
        )

    def execute_verification_aware_query(
        self,
        query_id: str,
        sql_string: str,
        snapshot_id: int,
        result_set: List[Dict[str, Any]],
        contributing_readings: List[Dict[str, Any]]
    ) -> VerificationAwareQueryObject:
        """Constructs a Verification-Aware Query Object combining query results with Merkle proofs.
        
        Fixes circular self-attestation by matching computed Merkle roots against 
        stored checkpoints in self.checkpointer, sorting nonces deterministically.
        """
        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
        
        if not contributing_readings:
            proof = {
                "total_rows_scanned": 0,
                "status_summary": {"VERIFIED": 0, "CHAIN_GAP": 0, "FAILED": 0},
                "merkle_root": "",
                "anchor_references": [],
                "proof_verified_independently": False
            }
            return VerificationAwareQueryObject(
                query_id=query_id,
                executed_at=now_iso,
                snapshot_id=snapshot_id,
                sql_string=sql_string,
                result_set=result_set,
                verification_proof=proof
            )

        # 1. Deterministic sorting by mpan, reading_ts, and etp_nonce
        sorted_readings = sorted(
            contributing_readings,
            key=lambda x: (x.get("mpan", ""), x.get("reading_ts", ""), x.get("etp_nonce", 0))
        )

        verified_count = sum(1 for r in sorted_readings if r.get("etp_verify_status") == "VERIFIED")
        gap_count = sum(1 for r in sorted_readings if r.get("etp_verify_status") == "CHAIN_GAP")
        failed_count = sum(1 for r in sorted_readings if r.get("etp_verify_status") not in ("VERIFIED", "CHAIN_GAP"))
        
        # 2. Recompute Merkle root over deterministically sorted block hashes
        hashes = [r["etp_block_hash"] for r in sorted_readings if "etp_block_hash" in r]
        computed_root = canonical_merkle_root(hashes) if hashes else ""

        # 3. Group readings by (mpan, day) and verify against stored checkpoints
        meter_days: Dict[Tuple[str, str], List[Dict[str, Any]]] = {}
        for r in sorted_readings:
            mpan = r.get("mpan", "UNKNOWN")
            ts = r.get("reading_ts", "")
            day = ts[:10] if len(ts) >= 10 else "UNKNOWN"
            meter_days.setdefault((mpan, day), []).append(r)

        anchor_refs = []
        all_checkpoints_valid = True
        
        for (mpan, day), group_readings in meter_days.items():
            group_hashes = [r["etp_block_hash"] for r in group_readings if "etp_block_hash" in r]
            group_root = canonical_merkle_root(group_hashes)
            
            # Find stored checkpoint in checkpointer (searching reversed to get the latest)
            cp_match = None
            for cp in reversed(self.checkpointer.checkpoints):
                if cp.get("mpan") == mpan and cp.get("day") == day:
                    cp_match = cp
                    break

            if cp_match:
                if cp_match.get("merkle_root") == group_root:
                    anchor_refs.append(cp_match.get("anchor_ref", ""))
                else:
                    all_checkpoints_valid = False
            else:
                all_checkpoints_valid = False

        # Proof is verified ONLY if zero failed rows AND all checkpoints exist & match recomputed roots
        independent_verification = (failed_count == 0) and all_checkpoints_valid and len(anchor_refs) > 0

        proof = {
            "total_rows_scanned": len(sorted_readings),
            "status_summary": {
                "VERIFIED": verified_count,
                "CHAIN_GAP": gap_count,
                "FAILED": failed_count
            },
            "merkle_root": computed_root,
            "anchor_references": list(set(anchor_refs)),
            "checkpoints_matched": len(anchor_refs),
            "total_meter_days": len(meter_days),
            "proof_verified_independently": independent_verification
        }

        return VerificationAwareQueryObject(
            query_id=query_id,
            executed_at=now_iso,
            snapshot_id=snapshot_id,
            sql_string=sql_string,
            result_set=result_set,
            verification_proof=proof
        )
