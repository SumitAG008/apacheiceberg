# Risk Register

Owned by `cto` (technical and security risks) and `cfo` (financial and commercial risks). Reviewed
in every `/audit`. Likelihood and impact are rated H/M/L.

The seed rows come from findings recorded in `SESSION_LOG.md`. Their current status is
**UNVERIFIED**: the first `/audit` must confirm whether each one is still open, citing code.

| ID | Risk | L | I | Owner | Mitigation | Status | Source | Review by |
|---|---|---|---|---|---|---|---|---|
| RSK-001 | Application audit trail is deletable (e.g. via `/v1/admin/reset-tenant`), which undermines the platform's own trust claims | M | H | cto | Append-only / hash-chained audit store; remove delete paths | Open (unverified) | SESSION_LOG.md, "Discovered but NOT yet resolved" §3 | 2026-10-10 |
| RSK-002 | No security headers (HSTS / CSP) at the edge | M | M | cto | Add headers at the edge and in API middleware; test for them | Open (unverified) | SESSION_LOG.md §3 | 2026-10-10 |
| RSK-003 | Competing CI/CD definitions (GitHub Actions, `azure-pipelines.yml`, Railway), so it's unclear which one gates production | M | M | release-engineer | Pick one gate of record; retire or document the others | Open (unverified) | SESSION_LOG.md §1, §3 | 2026-10-10 |
| RSK-004 | No dependency or container image scanning | M | H | release-engineer | `pip-audit`, `npm audit` and gitleaks in `code-quality.yml`; add Trivy for images | Mitigation added 2026-09-26 (report-only until baseline is clean) | SESSION_LOG.md §3 | 2026-10-10 |
| RSK-005 | Marketing and roadmap claims drift ahead of the code (the 92% roadmap scorecard) | H | H | gtm-lead | CLAIMS_REGISTER with evidence per claim; auditor checks it weekly | Mitigation added 2026-09-26 | "Investigation needed" session; NOVEMBER_GO_LIVE_ROADMAP.md | 2026-10-03 |
| RSK-006 | Plaintext credentials pasted into chats or committed to the repo | M | H | cto | Rotate anything exposed; gitleaks in CI; audit hook redacts secrets | Open | Setup session 2026-09-26 | 2026-10-03 |
| RSK-007 | Meter readings lost on restart: gateway acknowledges a block held only in memory and advances the nonce, so the meter can't resend; writer never persists to Iceberg; Kafka consumer discards malformed messages | H | H | cto | Durable-before-ack (DEC needed), writer persists to Iceberg, dead-letter topic; restart and DLQ tests (M3 exit criteria) | Open | `backend/etp/gateway.py:181-189`, `backend/etp/writer.py:80`, `backend/kafka_consumer.py:160-161` | 2026-10-09 |
| RSK-008 | `main` has no branch protection, so the "CI + review before main" rule is not enforced for pushes from a terminal | H | M | release-engineer | Founder enables branch protection (PR + required checks) | Open | GitHub API `branches/main` → `protected: false`; `9a7eaa3` pushed directly | 2026-09-28 |
