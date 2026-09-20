"""Block 4 — Phantom Grid Deception Honeypot.

Simulates plausible smart meter head-end telemetry responses for diverted traffic.
Generates time-of-day load curves, plausible error rates, and exports STIX 2.1 threat logs.
Isolated from production databases with zero egress routes.
"""

import time
import math
import random
import uuid
import datetime
import collections
import json
from pathlib import Path
from typing import Dict, Any, List

try:
    from backend.observability import audit
except ImportError:
    try:
        from observability import audit
    except ImportError:
        audit = None


class PhantomGridHoneypot:
    """Isolated deception honeypot for reconnaissance traffic with durable threat log persistence."""

    def __init__(self, max_sessions: int = 5000, max_logs: int = 10000, storage_path: str = "backend/data/etp_threat_logs.jsonl"):
        # Bounded sessions dictionary to prevent memory exhaustion from IP spoofing
        self.max_sessions = max_sessions
        self.sessions: Dict[str, Dict[str, Any]] = {}
        self.session_order = collections.deque()
        self.storage_path = storage_path
        # Bounded threat logs deque
        self.threat_logs = collections.deque(maxlen=max_logs)
        self._load_threat_logs()

    def _load_threat_logs(self) -> None:
        """Loads threat logs from JSON-lines file to guarantee durability across process restarts."""
        try:
            path = Path(self.storage_path)
            if path.exists():
                with open(path, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line:
                            self.threat_logs.append(json.loads(line))
        except Exception:
            pass

    def _append_threat_log(self, event: Dict[str, Any]) -> None:
        """O(1) append-only line writer to prevent disk DoS under high attacker request volume."""
        try:
            path = Path(self.storage_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "a", encoding="utf-8") as f:
                f.write(json.dumps(event) + "\n")
        except Exception:
            pass

    def _prune_sessions_if_needed(self):
        while len(self.sessions) > self.max_sessions and self.session_order:
            oldest_ip = self.session_order.popleft()
            self.sessions.pop(oldest_ip, None)

    def _generate_plausible_consumption(self, timestamp_epoch: float) -> float:
        """Derives a statistically plausible kWh consumption value following a time-of-day load curve."""
        dt = datetime.datetime.fromtimestamp(timestamp_epoch, datetime.timezone.utc)
        hour = dt.hour + (dt.minute / 60.0)
        
        # Diurnal load curve equation (morning peak at 8am, evening peak at 7pm)
        base_load = 0.200
        morning_peak = 0.350 * math.exp(-((hour - 8.0) ** 2) / 8.0)
        evening_peak = 0.450 * math.exp(-((hour - 19.0) ** 2) / 6.0)
        noise = random.uniform(-0.025, 0.025)
        
        return round(max(0.050, base_load + morning_peak + evening_peak + noise), 3)

    def handle_diverted_request(
        self,
        source_ip: str,
        requested_route: str,
        epoch_window: int,
        payload: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Handles a diverted request and returns a plausible synthetic acknowledgement."""
        now = time.time()
        
        # Track session duration for Attacker Containment Duration metric
        session_id = self.sessions.get(source_ip, {}).get("session_id")
        if not session_id:
            self._prune_sessions_if_needed()
            session_id = f"session_{uuid.uuid4().hex[:12]}"
            self.sessions[source_ip] = {
                "session_id": session_id,
                "first_seen": now,
                "request_count": 0
            }
            self.session_order.append(source_ip)

        session = self.sessions[source_ip]
        session["request_count"] += 1
        duration_s = now - session["first_seen"]

        # Plausible 0.5% transient error injection (prevent honeypot tell)
        if random.random() < 0.005:
            response = {
                "status": "transient_error",
                "error_code": "HES_BUSY_429",
                "retry_after_s": 15
            }
        else:
            synthetic_kwh = self._generate_plausible_consumption(now)
            response = {
                "status": "acknowledged",
                "ack_id": f"ack_{uuid.uuid4().hex[:16]}",
                "received_kwh": synthetic_kwh,
                "hes_timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat()
            }

        # Log threat intelligence event
        threat_event = {
            "event_id": f"evt_{uuid.uuid4().hex}",
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "source_ip": source_ip,
            "requested_route": requested_route,
            "epoch_window": epoch_window,
            "honeypot_session_id": session_id,
            "session_duration_s": round(duration_s, 2),
            "payload_sample": str(payload)[:200],
            "stix_export_status": "PENDING"
        }
        self.threat_logs.append(threat_event)
        self._append_threat_log(threat_event)

        if audit:
            audit.deny(action="etp.threat_log", reason="HONEYPOT_DECEIVE", detail=threat_event)
        
        return response

    def export_stix_21_bundle(self) -> Dict[str, Any]:
        """Serializes threat intelligence into STIX 2.1 JSON format for SIEM export."""
        indicators = []
        for log in self.threat_logs:
            indicators.append({
                "type": "indicator",
                "id": f"indicator--{uuid.uuid4()}",
                "created": log["timestamp"],
                "modified": log["timestamp"],
                "name": f"STIX Threat Scanner {log['source_ip']}",
                "pattern": f"[ipv4-addr:value = '{log['source_ip']}']",
                "pattern_type": "stix",
                "valid_from": log["timestamp"]
            })
            log["stix_export_status"] = "EXPORTED"

        return {
            "type": "bundle",
            "id": f"bundle--{uuid.uuid4()}",
            "objects": indicators
        }
