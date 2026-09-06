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
from typing import Dict, Any, List


class PhantomGridHoneypot:
    """Isolated deception honeypot for reconnaissance traffic."""

    def __init__(self):
        self.sessions: Dict[str, Dict[str, Any]] = {}
        self.threat_logs: List[Dict[str, Any]] = []

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
            session_id = f"session_{uuid.uuid4().hex[:12]}"
            self.sessions[source_ip] = {
                "session_id": session_id,
                "first_seen": now,
                "request_count": 0
            }

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
