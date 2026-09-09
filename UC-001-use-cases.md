# UC-001 — EnergyTrust Protocol: Comprehensive Use Cases

**Document ID:** UC-001  
**Version:** 2.1  
**Issued:** 2026-09-06T17:45:00Z  
**Status:** Approved Specification  

Legend: ● Buildable Now · ◐ Design Complete / Partial · ○ Planned Strategic Extension  

---

## 1. System Actors

| Actor | Type | Description | Security Privileges |
|---|---|---|---|
| **Smart Meter** | Edge Device | Physical smart meter with hardware Secure Element (SE). Emits signed telemetry blocks. | Hardware key execution only |
| **ETP Gateway** | Boundary Service | Ingestion proxy handling route verification, MTD rotation, and honeypot diversion. | Ingestion write access |
| **Attacker / Scanner** | External Adversary | Threat actor scanning networks, probing static URIs, or injecting replayed telemetry. | Zero authenticated access |
| **Settlement Analyst** | Internal User | Utility finance/settlement staff constructing and defending billing figures. | Read Gold & Verification views |
| **Grid Ops Engineer** | Internal User | Operational engineer investigating voltage anomalies, outages, and feeder assets. | Read Silver/Gold & Topology Graph |
| **SOC Security Analyst** | Internal User | Security operations staff monitoring threat intelligence and containment events. | Read Threat Logs & Graph |
| **Regulator / Auditor** | External Auditor | Third-party regulatory body (e.g., Ofgem) verifying settlement proofs independently. | Read-Only Audit & Verification API |
| **Consultant** | External User | Time-boxed contractor requiring restricted access to specific data namespaces. | Deny-by-default; namespace allowlist |
| **Platform Operator** | System Admin | Administrator overseeing system health, key rotation, and table retention policies. | Full Administrative Control |

---

## 2. Core Use Cases (UC-01 to UC-09)

### UC-01 — Verified Telemetry Ingestion ●
- **Primary Actor:** Smart Meter $\rightarrow$ ETP Gateway $\rightarrow$ Iceberg Lakehouse
- **Trigger:** Scheduled half-hourly telemetry push from smart meter.
- **Goal:** Ingest telemetry reading into Apache Iceberg with immutable cryptographic verification columns populated.
- **Preconditions:** Smart meter hardware initialized with shared route secret $K_{secret}$, active ECDSA keypair, and initialized monotonic nonce $N$.
- **Postconditions:** Reading recorded in `bronze_ami_readings` with `etp_verify_status = VERIFIED` and updated gateway nonce state.

```
Smart Meter            ETP Gateway            Nonce Store            Writer (Block 5)
    │                       │                      │                        │
    │ 1. Compute Route      │                      │                        │
    │ 2. Sign Telemetry     │                      │                        │
    ├──────────────────────►│                      │                        │
    │  POST /rotated_scramble│                      │                        │
    │                       │ 3. Check Route       │                        │
    │                       │ 4. Verify Nonce ────►│                        │
    │                       │◄─────────────────────┤                        │
    │                       │ 5. Verify Signature  │                        │
    │ 6. HTTP 200 OK        │ 6. Buffer Block      │                        │
    │◄──────────────────────┤                      ├───────────────────────►│
    │                       │                      │   Write Iceberg Batch  │
```

#### Step-by-Step Main Flow
1. Meter reads consumption data ($kWh$, voltage) and increments its internal monotonic nonce $N_{meter}$.
2. Meter calculates current epoch window $W = \lfloor t / 60 \rfloor$ and derives active route hash $S_{w} = \text{first}_{12\_hex}(\text{HMAC-SHA256}(K_{secret}, \text{uint64\_be}(W)))$.
3. Meter constructs block payload and hashes fields using standard byte canonicalization:
   $$H_{block} = \text{SHA256}(\text{mpan} \mathbin{\Vert} 0x1F \mathbin{\Vert} \text{reading\_kwh} \mathbin{\Vert} 0x1F \mathbin{\Vert} \text{timestamp} \mathbin{\Vert} 0x1F \mathbin{\Vert} \text{prev\_hash} \mathbin{\Vert} 0x1F \mathbin{\Vert} \text{nonce} \mathbin{\Vert} 0x1F \mathbin{\Vert} \text{crypto\_suite\_id} \mathbin{\Vert} 0x1F \mathbin{\Vert} \text{key\_id})$$
4. Meter signs $H_{block}$ inside its Secure Element producing ECDSA signature $\sigma$.
5. Meter issues `POST /api/v1/telemetry/rotated_<Sw>` containing payload.
6. Gateway checks route against active window set $\{W-1, W, W+1\}$. Route matches.
7. Gateway queries Nonce Store for $N_{last}$. Checks $N_{meter} > N_{last}$. Nonce valid.
8. Gateway computes $H_{block}$ and verifies signature $\sigma$ against meter public key. Signature valid.
9. Gateway updates Nonce Store with $N_{meter}$ and $H_{block}$.
10. Gateway passes block to Writer (Block 5) for micro-batched append to `bronze_ami_readings` with `etp_verify_status = VERIFIED`.
11. Gateway returns HTTP 200 OK to meter.

#### Alternate & Error Flows
- **A1 (Replay Attack):** Nonce $N_{meter} \le N_{last}$. Gateway immediately rejects request. Logs `telemetry.replay_rejected`. Block dropped.
- **A2 (Data Tampering):** Recomputed $H_{block}$ mismatch. Gateway rejects request, logs `telemetry.tamper_rejected`, and escalates meter to Stage S3 (Containment).
- **A3 (Invalid Signature):** Signature verification fails. Gateway rejects request, logs `telemetry.signature_invalid`, and escalates meter to S3.
- **A4 (Chain Discontinuity):** Block `prev_hash` does not match recorded $H_{last}$. Gateway accepts reading with `etp_verify_status = CHAIN_GAP` to preserve evidence of missing upstream data.
- **A5 (Expired Route):** Request hits route from window $W-2$ or older. Gateway diverts traffic to Phantom Grid (UC-03).

#### Acceptance Criteria & SLAs
- Replayed blocks rejected in $<1 \text{ ms}$ via single integer compare before ECDSA execution.
- Single-byte tampering detected at gateway boundary 100% of the time.
- System tolerates $\pm 60 \text{ s}$ clock drift without rejection.
- Gateway ingestion latency $p_{99} < 15 \text{ ms}$.

---

### UC-02 — Settlement Substantiation & Verification-Aware Queries ●
- **Primary Actor:** Settlement Analyst $\rightarrow$ Regulator / Auditor
- **Trigger:** Regulator audits a submitted monthly settlement figure or utility rate reconciliation.
- **Goal:** Produce an independently verifiable, cryptographically backed proof for a settlement query result using a **Verification-Aware Query Object**.
- **Preconditions:** Telemetry ingested into Iceberg; daily Merkle checkpoints anchored to external TSA.
- **Postconditions:** Single unified JSON response object generated containing query figures, snapshot ID, scanned partition hashes, and Merkle proof paths.

#### Main Flow & Verification-Aware Query Response
1. Analyst executes settlement query in Meldra Data Studio:
   ```sql
   SELECT mpan, SUM(reading_kwh) AS total_kwh 
   FROM gold_settlement_daily 
   WHERE settlement_date BETWEEN '2026-03-01' AND '2026-03-31' 
   GROUP BY mpan;
   ```
2. Engine executes query and returns a **Verification-Aware Query Object**:
   ```json
   {
     "query_id": "q_7f8a9b1c-2d3e-4f5a-6b7c-8d9e0f1a2b3c",
     "executed_at": "2026-09-06T17:45:00.120Z",
     "snapshot_id": 482910481290481,
     "sql_string": "SELECT mpan, SUM(reading_kwh)...",
     "result_set": [
       {"mpan": "MPAN-1200012345678", "total_kwh": 412.850}
     ],
     "verification_proof": {
       "total_rows_scanned": 1488,
       "status_summary": {"VERIFIED": 1488, "CHAIN_GAP": 0, "FAILED": 0},
       "merkle_root": "7b1f9c8e...",
       "anchor_reference": "tsa:2026-04-01T00:05:00Z:0a9b...",
       "proof_verified_independently": true
     }
   }
   ```
3. Analyst hands regulator the verification-aware query response object.
4. Auditor re-runs identical query against snapshot ID `482910481290481` using DuckDB/Trino and confirms Merkle root matches without vendor software.

---

### UC-03 — Reconnaissance Containment & Statistically Plausible Deception ●
- **Primary Actor:** Attacker $\rightarrow$ ETP Gateway $\rightarrow$ Phantom Grid
- **Trigger:** Attacker probes static endpoint (e.g., `/api/v1/telemetry`) or expired rotated route.
- **Goal:** Engages scanner in a **Statistically Plausible Deception** loop, maximizing **Attacker Containment Duration** while gathering threat intelligence.

```
Attacker               ETP Gateway            Phantom Grid            Threat Sentinel
   │                        │                      │                         │
   │ 1. Probe Expired Route │                      │                         │
   ├───────────────────────►│                      │                         │
   │                        │ 2. Route Lookup Fail │                         │
   │                        │ 3. Flag Source IP ───┼────────────────────────►│
   │                        │ 4. Silent Proxy      │                         │
   │                        ├─────────────────────►│                         │
   │                        │                      │ 5. Generate Plausible   │
   │ 6. HTTP 200 OK (Time-of-day profile)         │    Synthetic Telemetry  │
   │◄───────────────────────┴──────────────────────┤    + Jitter Jitter       │
   │                        │                      │ 7. One-Way Threat Log  │
   │                        │                      ├────────────────────────►│
```

#### Plausible Synthetic Response Generation
- **Time-of-Day Curve:** Consumption readings generated by Phantom Grid follow realistic load profiles (morning peak, mid-day valley, evening peak).
- **Plausible Error Injector:** Inject 0.5% transient $HTTP\ 429\ Rate\ Limited$ or $HTTP\ 503\ Service\ Unavailable$ responses to mimic real network conditions. (A 100% clean success rate is a honeypot tell).
- **Headline SLA Metric:** **Attacker Containment Duration** — target median engagement $> 12 \text{ minutes}$ before scanner abandons session.

---

### UC-09 — Monotonic Nonce Sequence Completeness & Omission Detection ○
- **Primary Actor:** Settlement Auditor $\rightarrow$ ETP Verifier Engine
- **Trigger:** Audit of suspected meter tampering or missing billing interval readings.
- **Goal:** Prove whether readings were **omitted or withheld** from the ledger, beyond row-level integrity checks.
- **Background / IP Note:** Merkle tree proofs verify that existing rows were not modified. They **cannot** detect missing rows. Monotonic nonces solve this: any gap in the sequence $N_{last} - N_{first} \ne \text{leaf\_count} - 1$ proves missing readings. *(Secondary patent application pending).*

#### Flow
1. Auditor requests completeness verification for `mpan` over target billing month.
2. Verifier queries `_etp_checkpoints` for target period:
   ```sql
   SELECT day, mpan, first_nonce, last_nonce, leaf_count, gap_count
   FROM _etp_checkpoints
   WHERE mpan = 'MPAN-1200012345678' AND day BETWEEN '2026-03-01' AND '2026-03-31';
   ```
3. If `gap_count > 0`, system isolates exact missing nonces (e.g., nonces 184203–184205 omitted).
4. Verifier emits `CompletenessReport` identifying withheld readings with cryptographic certainty.

---

## 3. Strategic Extensions (UC-10 to UC-13)

### UC-10 — Automated Tariff & Settlement Dispute Resolution ○
- **Primary Actor:** Utility Billing System $\rightarrow$ Commercial Customer
- **Trigger:** High-value industrial customer disputes peak demand tariff charges.
- **Goal:** Execute automated time-stamped verification of interval consumption during peak tariff windows.

### UC-11 — Multi-Tenant Isolation & Cross-DNO Data Exchange ○
- **Primary Actor:** Regional Distribution Network Operators (DNO A & DNO B)
- **Trigger:** Boundary feeder energy exchange balancing.
- **Goal:** Share verified boundary telemetry between independent DNOs without data leakage.

### UC-12 — Zero-Trust OTA Firmware Verification ○
- **Primary Actor:** Gateway Operations $\rightarrow$ Smart Meters
- **Trigger:** Over-the-air (OTA) firmware deployment.
- **Goal:** Ensure firmware images deployed to edge meters carry cryptographically verifiable audit logs into Iceberg.

### UC-13 — Synthetic Threat Intelligence Export to SIEM (STIX/TAXII) ○
- **Primary Actor:** Phantom Grid Deception Engine $\rightarrow$ Enterprise SOC SIEM
- **Trigger:** High-volume scanner engagement with Phantom Grid.
- **Goal:** Export real-time attack patterns, IP ranges, and payload signatures to enterprise SOC tools (Splunk, Sentinel).

### UC-14 — AI Low-Voltage Grid Digital Twin: Feeder Headroom & Phase Inference ●
- **Primary Actor:** DNO Grid Planning Engineer $\rightarrow$ Meldra AI Digital Twin
- **Trigger:** EV/Heat pump connection request, solar export assessment, or annual network capacity review under RIIO-ED2.
- **Goal:** Fuses physical CIM topology with Iceberg smart meter telemetry to calculate real-time feeder headroom, detect reverse power flow, and infer unmeasured meter phase assignments ($L1, L2, L3$) via topological embeddings in sub-second latency.

---

## 4. Traceability Matrix

| Use Case | Title | HLD Block | LLD Function / Contract | Iceberg Table | Test Matrix ID |
|---|---|---|---|---|---|
| **UC-01** | Telemetry Ingestion | Blocks 1, 2, 3, 5 | `active_routes()`, `verify_block()` | `bronze_ami_readings` | T1, T2, T4, T5, T6 |
| **UC-02** | Settlement Audit | Blocks 5, 6, 7 | `verify_settlement_proof()` | `_etp_checkpoints` | T10, T11, T12 |
| **UC-03** | Recon Containment | Blocks 2, 3, 4 | `active_routes()`, `proxy_phantom()` | `_etp_threat_log` | T3, T8, T9 |
| **UC-04** | Grid Investigation | Blocks 5, Query | `execute_cypher_topology()` | `gold_settlement_daily` | T15 |
| **UC-05** | Compromise Recovery| Blocks 1, 3 | `revoke_meter_key()` | `_etp_audit_log` | T16 |
| **UC-06** | PQC Migration | Blocks 1, 3 | `verify_pqc_signature()` | `bronze_ami_readings` | T17 |
| **UC-07** | Consultant Access | Query / RBAC | `check_tenant_scope()` | All namespaces | T18 |
| **UC-08** | Daily Checkpoint | Block 6 | `build_merkle_tree()` | `_etp_checkpoints` | T10, T12 |
| **UC-09** | Completeness Check| Block 7 | `check_nonce_continuity()` | `_etp_checkpoints` | T19 |
| **UC-10** | Tariff Disputes | Block 7, Query | `verify_interval_proof()` | `gold_settlement_daily` | T20 |
| **UC-11** | Cross-DNO Exchange | Query / RBAC | `enforce_dno_isolation()` | `silver_ami_readings` | T21 |
| **UC-12** | Firmware Audit | Blocks 1, 3, 5 | `verify_firmware_block()` | `bronze_ami_readings` | T22 |
| **UC-13** | STIX/TAXII Export | Block 4, Sentinel| `export_stix_telemetry()` | `_etp_threat_log` | T23 |
| **UC-14** | AI LV Digital Twin | Graph / Query / AI| `generate_node_embeddings()`, `partition_graph_quantum()` | `gold_settlement_daily` | T24, T25 |

---

## 5. Document Control

| Version | Date | Author | Summary of Changes |
|---|---|---|---|
| 1.0 | 2026-09-06T09:10:00Z | Lead Architect | Initial Baseline |
| 2.0 | 2026-09-06T17:36:00Z | Lead Architect | Added detailed flows, SLAs, UC-10–UC-13, and Traceability Matrix |
| 2.1 | 2026-09-06T17:45:00Z | Lead Architect | Added Verification-Aware Query Objects (UC-02), Plausible Deception (UC-03), and Nonce Omission Detection (UC-09) |
