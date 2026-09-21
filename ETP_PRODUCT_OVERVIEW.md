# ETP (Energy Telemetry Provenance) — Product Overview & Layman's Guide

## 1. What Are We Building? (Layman's Explanation)

Every 30 minutes, millions of smart electricity meters in homes, factories, and solar farms record how much power is used or generated. 

### The Hidden Problem in Utility Data Lakes
Current utility infrastructure encrypts data while it travels over the internet. However, **once that data arrives inside a company's database or cloud data lake, its proof of truth is lost**:
- An insider or rogue script can alter numbers to fake lower electricity bills.
- Worse still, someone can **silently delete missing readings** (e.g., storing only 42 half-hourly readings instead of 48) to conceal power theft or unbilled energy losses.
- Traditional security proves *who* sent a message, but **it cannot prove if data was deleted or tampered with after arrival**.

### Our Solution: The Digital Tamper-Proof Notary
ETP (Energy Telemetry Provenance) is a high-performance software engine that acts like an **unforgeable digital notary** for energy telemetry:

1. **Per-Reading Seal:** Every 30-minute reading is sealed with a unique cryptographic fingerprint (SHA-256 block hash and ECDSA digital signature).
2. **Daily Merkle Chain:** All 48 half-hourly readings for a meter-day are chained into a Merkle tree and stamped with an official RFC 3161 external time clock (TSA timestamp).
3. **Instant Omission Detection:** If even *one single reading* is removed, missing, or altered, ETP immediately flags it (`ANCHORED_WITH_GAPS`).
4. **Verified AI Ground Truth:** When an AI model or analyst asks, *"How much power was used on September 20?"*, ETP returns the calculation **plus an unforgeable cryptographic proof** verifying zero data was deleted or altered.

---

## 2. Core Technical Architecture & Achievements

### High-Performance Native Core (`libetp_core` C++20 & Python)
- **Zero-Throw Hex Parsing:** High-speed string parsing with zero memory allocations or exception overhead.
- **RAII OpenSSL Ownership:** Fully managed `EVP_PKEY`, `EVP_MD_CTX`, and `BIO` handles ensuring zero memory leaks under stress.
- **Locale-Independent Precision:** `std::to_chars` float formatting guaranteeing identical hashes across global deployments.

### Omission & Revenue Protection Engine (UC-09)
- **Same-Day End Truncation Detection:** Verifies whether 48/48 half-hourly readings were received. Detects missing trailing readings (e.g., 42/48) as well as mid-day missing nonces.
- **Authenticated Metadata Commitment:** Hashes Merkle roots, sequence nonces, leaf counts, and boundary gaps into a single RFC 3161 timestamp envelope.

### Attacker Deception Honeypot ("Phantom Grid" UC-03)
- **Automated Traffic Diversion:** Diverts malicious scanners or unauthorized probes into an isolated synthetic honeypot.
- **$O(1)$ JSON-Lines Persistence:** Logs threat intelligence events to `etp_threat_logs.jsonl` in constant time, preventing disk I/O DoS attacks.
- **STIX 2.1 Intelligence Export:** Standardized threat export for Enterprise Security Operations Centers (SOCs).

### Verification-Aware Query Objects (UC-02)
- Extends analytical SQL query responses with a complete provenance proof payload (`query_id`, `snapshot_id`, `sql_string`, `merkle_root`, `anchor_references`, `proof_verified_independently`).

---

## 3. Product Roadmap & Strategic Positioning

> **"Reasoning is rented; verified ground truth is owned."**

```
+-------------------------------------------------------------------------+
|                          PRODUCT ROLLOUT STAGES                         |
+-------------------------------------------------------------------------+
| STAGE 1: Lead with UC-09 (Omission Detection / Revenue Protection)     |
|   -> Targets existing line-item budgets (Unbilled Energy / Theft)       |
|   -> Zero hardware upgrades, zero meter firmware dependencies           |
|   -> Package as standalone library `etp-verify` on PyPI                  |
+-------------------------------------------------------------------------+
| STAGE 2: Expand to UC-02 (Verification-Aware Query Engine)             |
|   -> Verifiable ground truth for autonomous AI agents & analytics       |
+-------------------------------------------------------------------------+
| STAGE 3: Secondary Hook UC-03 (Phantom Grid OT Deception)              |
|   -> High-impact SOC demo for defense & critical infrastructure          |
+-------------------------------------------------------------------------+
```

---

## 4. Verification & Testing Matrix

- **Unit & Integration Test Suite:** 48/48 test cases passing cleanly (100% green).
- **Golden Vector Conformance Suite:** `tools/gen_golden_vectors.py` dynamically derives authoritative test vectors (`golden_vectors.json`), preventing hand-written constant drift between C++ and Python.
- **CI/CD Automation:** Fully integrated GitHub Actions workflow running both Python Pytest suites and native C++20 `cmake` builds.
