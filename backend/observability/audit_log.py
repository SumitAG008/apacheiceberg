# Copyright (c) 2026 Meldra AI Ltd. All rights reserved.
"""
observability/audit_log.py — structured, timestamped audit and error log.

WHY THIS EXISTS
---------------
Under NIS Regulations 2018 (as an Operator of Essential Services or a
supplier to one), the NCSC Cyber Assessment Framework objective B / C, and
the DCC Smart Energy Code security obligations, a platform touching grid or
metering data has to be able to answer, months later:

    "On 14 March at 02:11 UTC, who read which table, under which role,
     from which tenant, and what did the platform decide?"

Free-text `logger.info("query ran")` cannot answer that. Every record
emitted here is a single JSON object on one line with a UTC ISO-8601
timestamp to millisecond precision, so it can be shipped straight into
Splunk / Elastic / CloudWatch and queried without parsing rules.

DESIGN RULES
------------
1. Append-only. Nothing in this module updates or deletes a record.
2. Never log data values. Column *names* yes; cell contents never. An audit
   log that contains the PII it is auditing is a second breach surface.
3. Never log secrets. `redact()` is applied to every payload.
4. Failure to log an ALLOW is tolerable; failure to log a DENY is not —
   deny/error records are flushed immediately.
5. Timestamps are UTC with an explicit trailing Z. Local time in an audit
   trail is a finding at assessment.

USAGE
-----
    from observability.audit_log import audit, AuditEvent

    audit.record(
        AuditEvent(
            action="query.execute",
            outcome="allow",
            tenant_id=tenant,
            role=role,
            subject=user_id,
            resource=f"{namespace}.{table_name}",
            detail={"mode": "sql", "rows": 1420, "duration_ms": 88},
        )
    )
"""

from __future__ import annotations

import json
import logging
import os
import socket
import sys
import threading
import traceback
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Dict, Optional

# ─── Constants ────────────────────────────────────────────────────────────

SCHEMA_VERSION = "1.0"

#: Keys whose values are replaced with a placeholder before serialisation.
_REDACT_KEYS = {
    "password", "passwd", "secret", "token", "api_key", "apikey",
    "authorization", "auth", "anthropic_api_key", "aws_secret_access_key",
    "client_secret", "private_key", "totp", "mfa_code", "session",
}

_REDACTED = "***REDACTED***"

#: Outcomes are a closed set so dashboards can group on them reliably.
OUTCOME_ALLOW = "allow"
OUTCOME_DENY = "deny"
OUTCOME_ERROR = "error"

_HOSTNAME = socket.gethostname()


def utc_now_iso() -> str:
    """UTC ISO-8601 with millisecond precision and an explicit Z suffix."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + \
        f"{datetime.now(timezone.utc).microsecond // 1000:03d}Z"


def redact(payload: Any) -> Any:
    """Recursively replace sensitive values. Applied to every record."""
    if isinstance(payload, dict):
        return {
            k: (_REDACTED if k.lower() in _REDACT_KEYS else redact(v))
            for k, v in payload.items()
        }
    if isinstance(payload, (list, tuple)):
        return [redact(v) for v in payload]
    return payload


# ─── Event ────────────────────────────────────────────────────────────────

@dataclass
class AuditEvent:
    """One auditable decision or failure.

    Args:
        action:     Dotted verb, e.g. "query.execute", "table.create",
                    "rbac.check", "auth.login", "snapshot.expire".
        outcome:    OUTCOME_ALLOW | OUTCOME_DENY | OUTCOME_ERROR.
        tenant_id:  Tenant the request belonged to. "" means unscoped —
                    which on a data path is itself worth alerting on.
        role:       RBAC role the decision was evaluated against.
        subject:    Authenticated user id (JWT `sub`), not an email.
        resource:   "namespace.table", graph name, or endpoint path.
        detail:     Non-sensitive structured context. Never cell values.
        request_id: Correlates every record produced by one HTTP request.
    """

    action: str
    outcome: str
    tenant_id: str = ""
    role: str = ""
    subject: str = ""
    resource: str = ""
    detail: Dict[str, Any] = field(default_factory=dict)
    request_id: str = ""
    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: str = field(default_factory=utc_now_iso)

    def to_json(self) -> str:
        record = asdict(self)
        record["detail"] = redact(record["detail"])
        record["schema_version"] = SCHEMA_VERSION
        record["host"] = _HOSTNAME
        record["service"] = os.environ.get("MELDRA_SERVICE_NAME", "meldra-api")
        record["env"] = os.environ.get("MELDRA_ENV", "development")
        return json.dumps(record, separators=(",", ":"), default=str, sort_keys=True)


# ─── Sink ─────────────────────────────────────────────────────────────────

class AuditLog:
    """Thread-safe JSON-lines audit sink.

    Writes to a rotating file when MELDRA_AUDIT_LOG_PATH is set, and always
    mirrors to stdout so containerised deployments capture it without a
    volume mount. Deny and error records are flushed synchronously.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._logger = logging.getLogger("meldra.audit")
        self._logger.setLevel(logging.INFO)
        self._logger.propagate = False

        if not self._logger.handlers:
            stream = logging.StreamHandler(sys.stdout)
            stream.setFormatter(logging.Formatter("%(message)s"))
            self._logger.addHandler(stream)

            path = os.environ.get("MELDRA_AUDIT_LOG_PATH")
            if path:
                from logging.handlers import RotatingFileHandler
                os.makedirs(os.path.dirname(path), exist_ok=True)
                rotating = RotatingFileHandler(
                    path,
                    maxBytes=int(os.environ.get("MELDRA_AUDIT_MAX_BYTES", 50 * 1024 * 1024)),
                    backupCount=int(os.environ.get("MELDRA_AUDIT_BACKUPS", 20)),
                    encoding="utf-8",
                )
                rotating.setFormatter(logging.Formatter("%(message)s"))
                self._logger.addHandler(rotating)

    def record(self, event: AuditEvent) -> str:
        """Emit an event. Returns its event_id for correlation."""
        line = event.to_json()
        with self._lock:
            self._logger.info(line)
            if event.outcome in (OUTCOME_DENY, OUTCOME_ERROR):
                for h in self._logger.handlers:
                    h.flush()
        return event.event_id

    # ── Convenience wrappers ─────────────────────────────────────────────

    def allow(self, action: str, **kw: Any) -> str:
        return self.record(AuditEvent(action=action, outcome=OUTCOME_ALLOW, **kw))

    def deny(self, action: str, reason: str, **kw: Any) -> str:
        detail = kw.pop("detail", {}) or {}
        detail["reason"] = reason
        return self.record(
            AuditEvent(action=action, outcome=OUTCOME_DENY, detail=detail, **kw)
        )

    def error(self, action: str, exc: BaseException, **kw: Any) -> str:
        """Record a failure with type, message and traceback.

        The traceback is capped so a pathological recursion cannot flood the
        audit store — truncation is marked explicitly rather than silent.
        """
        detail = kw.pop("detail", {}) or {}
        tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        if len(tb) > 8000:
            tb = tb[:8000] + "\n...[traceback truncated at 8000 chars]"
        detail.update({
            "error_type": type(exc).__name__,
            "error_message": str(exc)[:2000],
            "traceback": tb,
        })
        return self.record(
            AuditEvent(action=action, outcome=OUTCOME_ERROR, detail=detail, **kw)
        )


#: Module-level singleton. Import this, not the class.
audit = AuditLog()


__all__ = [
    "audit", "AuditLog", "AuditEvent", "utc_now_iso", "redact",
    "OUTCOME_ALLOW", "OUTCOME_DENY", "OUTCOME_ERROR", "SCHEMA_VERSION",
]
