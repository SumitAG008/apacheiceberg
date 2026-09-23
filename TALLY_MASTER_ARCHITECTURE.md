# Tally Master Architecture & Data Governance Specification

**Document Version:** 1.0.0  
**Timestamp Standard:** ISO-8601 GMT / UTC (`YYYY-MM-DDTHH:MM:SS.fffZ`)  
**Status:** Canonical Platform Architecture  

---

## 1. Executive Data Scale & Golden Principle

### 1.1 Scale Baseline (3 Million Meters Estate at 48 Half-Hourly Settlement Periods/Day)

| Data Component | Daily Volume | Annual Volume | Target Storage Engine | Access Policy |
| :--- | :--- | :--- | :--- | :--- |
| **Raw Interval Telemetry** | 144,000,000 rows | 52.6 Billion rows | Apache Iceberg (`bronze_ami_readings`) | **UI NEVER READS DIRECTLY** |
| **Daily Merkle Checkpoints** | 3,000,000 rows | 1.1 Billion rows | Apache Iceberg (`_etp_checkpoints`) | Read by reference |
| **Meter-Days with Gaps** (at 2%) | 60,000 rows | 21.9 Million rows | PostgreSQL (`omission_case`) | Processing engine |
| **Open Dispute Work Queue** | ~200 cases | 73,000 cases | PostgreSQL (`omission_case`) | **UI READS HERE** |

### 1.2 The Golden Interface Principle
> *"The interface never queries the raw telemetry corpus. It queries a work queue. 144 million rows arrive daily; an operator looks at about two hundred. Everything in the architecture exists to reduce the first number to the second."*

---

## 2. Three-Tier Storage Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ 1 · CORPUS LAYER (Apache Iceberg — Append-Only, 144M/day)                   │
│     bronze_ami_readings · 52.6B rows/year · UI NEVER READS DIRECTLY          │
└─────────────────────────────────────────────────────────────────────────────┘
                                   │
                    (Nightly Checkpoint Job)
                                   ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ 2 · EVIDENCE LAYER (Apache Iceberg — Merkle Roots & TSA Anchors, 3M/day)   │
│     _etp_checkpoints & _etp_threat_log · READ BY REFERENCE                  │
└─────────────────────────────────────────────────────────────────────────────┘
                                   │
                    (gap_count > 0 Opens Dispute Case)
                                   ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ 3 · WORK QUEUE & MASTER DATA LAYER (PostgreSQL + Apache AGE — ~200 Open)     │
│     omission_case · usage_point · meter · network_asset · UI READS HERE     │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 3. Entity Hierarchy & Universal GMT/Geo Schema Standard

### 3.1 Six-Level Entity Hierarchy
* **L1 (Tenant Scope):** `tenant` (Root scope boundary)
* **L2 (Estate & Security):** `estate`, `role`, `app_user`, `network_asset`
* **L3 (Pivot Object):** `usage_point` (MPAN/MPRN/NMI supply point), `rbac_policy`, `row_filter`, `network_edge`
* **L4 (Devices & Work Triage):** `meter`, `omission_case` (Work queue item), `checkpoint` (Iceberg evidence)
* **L5 (Registers & Keys):** `meter_register`, `meter_key` (Append-only key history), `reading_type`
* **L6 (Raw Wire Telemetry):** `reading` (`bronze_ami_readings` in Iceberg)

### 3.2 GMT Timestamp & Spatial Geolocation Requirements
Every record written to PostgreSQL or Apache Iceberg tables MUST carry:
1. `runtime_saved_at`: ISO-8601 timestamp in **GMT / UTC** (`TIMESTAMPTZ`, default `now() AT TIME ZONE 'UTC'`).
2. `latitude` & `longitude`: Spatial WGS84 decimal coordinates (`DECIMAL(9,6)`).
3. `geo_h3_index`: Hexagonal Spatial Index for spatial aggregation.

---

## 4. Four-Layer Security & Database-Enforced Tenant Isolation

### 4.1 Four Security Layers
1. **Layer 1 — Object & Action Grant (`rbac_object_grant`):**
   Gates access to screens and endpoints (`UsagePoint`, `OmissionCase`, `Reading`, `Checkpoint`).
2. **Layer 2 — Row Filter (`rbac_row_filter`):**
   Applies row-level predicates per role (`estate_id = ANY(:user_estates)`).
3. **Layer 3 — Column Mask (`rbac_column_mask`):**
   Redacts or hashes sensitive PII fields (`hidden`, `partial`, `hashed`).
4. **Layer 4 — HARD TENANT SCOPE (PostgreSQL Row Level Security):**
   Database-level Row Level Security (RLS) policy bound to verified JWT session variables.

### 4.2 Database-Enforced Multi-Tenant Partitioning Rules

```sql
-- PostgreSQL Row Level Security (RLS) — Database Guarantee, NOT Application Code
ALTER TABLE omission_case ENABLE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON omission_case
  USING (tenant_id = current_setting('app.tenant_id')::uuid);

-- Executed once per connection/request from verified JWT:
SET LOCAL app.tenant_id = 'a1b2c3d4-e5f6-7890-abcd-1234567890ab';
```

| Data Store | Partitioning & Isolation Strategy | Rationale & Enterprise Benefit |
| :--- | :--- | :--- |
| **PostgreSQL** | **Row Level Security (RLS)** (`ENABLE ROW LEVEL SECURITY`) | Gated at database engine level. Query omissions in application code can **never** leak cross-tenant data. |
| **Apache Iceberg** | **Namespace per Tenant** (`<tenant_id>__bronze.bronze_ami_readings`) | Supports "Bring Your Own Bucket" (BYOB) & Polaris Credential Vending for customer data sovereignty. |
| **Redis** | **Prefixed Keys** (`etp:{tenant_id}:meter:{mpan}`) | Eliminates key collisions across global meter identifiers (e.g. AU NMI vs GB MPAN). |
| **Apache AGE** | **Graph per Tenant** (`<tenant_id>__topology_graph`) | Prevents mandatory-filter graph traversal leaks across customer utility boundaries. |

### 4.3 Two-Level Tenant vs. Estate Hierarchy (Analytics ISV Model)
For Analytics ISVs (e.g. Amperon, Grid4C) serving multiple utility clients:
* `tenant_id` = **Who pays you** (the Analytics ISV account).
* `estate_id` = **Whose meters these are** (individual utility clients of the ISV).
* **RBAC Rule:** An ISV super-user sees all estates under their tenant; a utility user sees strictly their assigned `estate_id`.

---

## 5. UI Screen to Master Object Driving Map

| Screen | Driving Master Object | Granted Actions | Row Filter Scope | UI Target |
| :--- | :--- | :--- | :--- | :--- |
| **Meters & Estate** | `UsagePoint` | `read`, `export` | `tenant_id` + `estate_id` | `#chat-tab` |
| **Telemetry Feed** | `Reading` | `read` | `tenant_id` | `#telemetry-feed-tab` |
| **Checkpoints & Anchors** | `Checkpoint` | `read`, `verify` | `tenant_id` | `#checkpoints-tab` |
| **Omission Register** | `OmissionCase` | `read`, `update`, `assign`, `close` | `tenant_id` + `owner_id` | `#omissions-tab` |
| **Network Model** | `NetworkAsset` | `read` | `tenant_id` | `#graph-tab` |
| **Audit Ledger** | `AuditEvent` | `read` | `tenant_id` | `#audit-tab` |
| **Roles & Access** | `Role` | `read`, `write` | `tenant_id` | `#users-tab` |
| **Catalog & Connections** | `CatalogTable` | `read`, `write` | `tenant_id` | `#ingest-tab` |
| **Observability** | `ApiTraffic` | `read` | Platform Admin | `#traffic-tab` |
| **Schema Explorer** | `SchemaModel` | `read` | Internal Platform Eng | `#schema-explorer-tab` |

*Dynamic Navigation:* The sidebar navigation menu items render directly from the user's role permission table. Menu items for un-granted objects are **omitted from the API response payload**, never sent to the client.

---

## 6. AI / Machine Learning Governance

## 7. Field Governance & Extensibility Rules

### 7.1 Provenance-Bearing vs. Annotation Field Classification
The platform strictly distinguishes between cryptographic provenance-bearing fields and annotation metadata:

* **Canonical Wire Hash String (Fixed Byte Order):**
  $$\text{HashInput} = \text{mpan} \mathbin{\unicode{x241F}} \text{reading\_kwh} \mathbin{\unicode{x241F}} \text{timestamp} \mathbin{\unicode{x241F}} \text{prev\_hash} \mathbin{\unicode{x241F}} \text{nonce} \mathbin{\unicode{x241F}} \text{crypto\_suite\_id} \mathbin{\unicode{x241F}} \text{key\_id}$$

| Field Category | Target Fields | Modification / Extension Rules |
| :--- | :--- | :--- |
| **Provenance-Bearing** *(Inside Hash)* | `reading_kwh`, `nonce`, `timestamp`, `mpan`, `prev_hash`, `crypto_suite_id`, `key_id` | **NON-NEGOTIABLE / UNCHANGEABLE.** Adding or modifying a signed field breaks historical verification. Requires a new `crypto_suite_id` protocol version update (Meldra core engineering only). |
| **Annotation Metadata** *(Outside Hash)* | `cost_centre`, `internal_ref`, `case_notes`, `tags`, `priority`, `extensions` | **EXTENSIBLE BY PERMISSION.** Safe by design—cryptographic proofs and Merkle tree roots do not depend on annotation fields. |

### 7.2 Automated Field Triage & Approval Workflow
```
[ 1. Requester Submits Custom Field Request ]
                      │
                      ▼
[ 2. Auto-Triage: Touches Canonical Hash? ] ──(YES)──► AUTO-REJECT & Route to Protocol Team
                      │ (NO)
                      ▼
[ 3. Personal Data / PII Check? ] ─────────────(YES)──► Requires DPIA & Compliance Sign-Off
                      │ (NO)
                      ▼
[ 4. Tenant Admin Approval by Class ]
                      │
                      ▼
[ 5. Provision in custom_field_def Registry ] ──► Extends extensions JSONB column (NO DDL ALTER)
                      │
                      ▼
[ 6. Default Access: HIDDEN ] ──────────────────► Granted explicitly per role by Tenant Admin
```

### 7.3 Custom Field Registry Schema & Zero-Migration Architecture
Tenant custom fields are provisioned dynamically via `custom_field_def` rows and stored inside an `extensions JSONB` column. **`ALTER TABLE` is NEVER executed per tenant.**

```sql
CREATE TABLE custom_field_def (
  field_id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id         UUID NOT NULL,
  object_name       TEXT NOT NULL,               -- OmissionCase | UsagePoint | Meter
  field_key         TEXT NOT NULL,               -- e.g. cost_centre
  data_type         TEXT NOT NULL,               -- text | number | date | enum | bool
  label             TEXT NOT NULL,               -- e.g. "Cost Centre"
  enum_values       TEXT[],
  is_personal_data  BOOLEAN NOT NULL DEFAULT false,
  mask_default      TEXT NOT NULL DEFAULT 'hidden',
  retention_days    INT,                        -- Mandatory when is_personal_data IS TRUE
  status            TEXT NOT NULL,               -- requested | approved | live | retired
  requested_by      UUID NOT NULL,
  approved_by       UUID,
  justification     TEXT NOT NULL,
  created_at        TIMESTAMPTZ NOT NULL DEFAULT (now() AT TIME ZONE 'UTC'),
  runtime_saved_at  TIMESTAMPTZ NOT NULL DEFAULT (now() AT TIME ZONE 'UTC'),
  UNIQUE (tenant_id, object_name, field_key)
);

-- Extensible Master & Work Queue Tables carry a GIN-indexed extensions JSONB column:
ALTER TABLE omission_case ADD COLUMN IF NOT EXISTS extensions JSONB NOT NULL DEFAULT '{}';
CREATE INDEX IF NOT EXISTS idx_omission_case_extensions ON omission_case USING GIN (extensions);
```

