"""Estate master data schema.

Creates the `estate` schema holding the master data and work-queue tables that
every ETP screen reads from. Follows the same idempotent pattern as
`auth_db.init_auth_schema()` and is called alongside it on FastAPI startup.

Design notes
------------
* Business keys (`identifier`) are market-neutral: MPAN, MPRN, NMI and ESIID all
  fit. Never used as a foreign key target — supply points transfer between
  suppliers and are occasionally reused.
* `meter_key` is append-only. A proof taken in 2026 must re-verify in 2029 using
  the key that was valid when the block was signed, so rows are never updated or deleted.
* `settlement_calendar` carries `expected_periods` per day because GB clock-change
  days have 46 and 50 periods, not 48.
* Row Level Security binds tenant scope from `app.tenant_id`, set per request from
  the verified JWT. Tenant isolation is a database guarantee, not an application
  promise — a forgotten WHERE clause cannot leak across customers.
"""

import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

ESTATE_SCHEMA_SQL = """
CREATE SCHEMA IF NOT EXISTS estate;

-- ─── L1 · Tenancy ────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS estate.tenant (
    tenant_id     UUID PRIMARY KEY,
    name          TEXT        NOT NULL,
    tenant_type   TEXT        NOT NULL,              -- supplier | dno | isv | si
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS estate.estate (
    estate_id           UUID PRIMARY KEY,
    tenant_id           UUID NOT NULL REFERENCES estate.tenant(tenant_id),
    name                TEXT NOT NULL,
    market_code         VARCHAR(8) NOT NULL DEFAULT 'GB',
    expected_sp_per_day SMALLINT   NOT NULL DEFAULT 48,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_estate_tenant ON estate.estate (tenant_id);

-- ─── L2 · Physical premises and grid ─────────────────────────────────────────
CREATE TABLE IF NOT EXISTS estate.service_location (
    service_location_id UUID PRIMARY KEY,
    tenant_id           UUID NOT NULL REFERENCES estate.tenant(tenant_id),
    address_line        TEXT,
    postcode            VARCHAR(16),
    latitude            NUMERIC(9,6),
    longitude           NUMERIC(9,6)
);
CREATE INDEX IF NOT EXISTS ix_svcloc_tenant ON estate.service_location (tenant_id);

CREATE TABLE IF NOT EXISTS estate.network_asset (
    network_asset_id UUID PRIMARY KEY,
    tenant_id        UUID NOT NULL REFERENCES estate.tenant(tenant_id),
    asset_type       TEXT NOT NULL,   -- gsp | primary | hv_feeder | distribution | lv_feeder
    cim_class        TEXT,            -- Substation | ACLineSegment
    name             TEXT NOT NULL,
    voltage_kv       NUMERIC(8,3),
    gsp_group        CHAR(2)
);
CREATE INDEX IF NOT EXISTS ix_netasset_tenant ON estate.network_asset (tenant_id, asset_type);

-- Self-referencing topology. Versioned: the network is re-configured over time.
CREATE TABLE IF NOT EXISTS estate.network_edge (
    tenant_id  UUID NOT NULL REFERENCES estate.tenant(tenant_id),
    parent_id  UUID NOT NULL REFERENCES estate.network_asset(network_asset_id),
    child_id   UUID NOT NULL REFERENCES estate.network_asset(network_asset_id),
    relation   TEXT NOT NULL,          -- SUPPLIES | SERVES
    valid_from DATE NOT NULL,
    valid_to   DATE,
    PRIMARY KEY (parent_id, child_id, valid_from)
);
CREATE INDEX IF NOT EXISTS ix_netedge_child ON estate.network_edge (child_id);

-- ─── L3 · The pivot ──────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS estate.usage_point (
    usage_point_id      UUID PRIMARY KEY,
    tenant_id           UUID NOT NULL REFERENCES estate.tenant(tenant_id),
    estate_id           UUID NOT NULL REFERENCES estate.estate(estate_id),
    identifier          VARCHAR(64) NOT NULL,   -- MPAN | MPRN | NMI | ESIID
    identifier_scheme   VARCHAR(24) NOT NULL,   -- gb-mpan | gb-mprn | au-nmi | us-esiid
    identifier_bucket   SMALLINT    NOT NULL,   -- sha256(identifier) % 16, Iceberg partition key
    service_location_id UUID REFERENCES estate.service_location(service_location_id),
    network_asset_id    UUID REFERENCES estate.network_asset(network_asset_id),  -- serving LV feeder
    profile_class       CHAR(2),
    gsp_group           CHAR(2),
    energised_from      DATE NOT NULL,
    energised_to        DATE,
    UNIQUE (identifier, identifier_scheme, energised_from)
);
CREATE INDEX IF NOT EXISTS ix_up_tenant     ON estate.usage_point (tenant_id, estate_id);
CREATE INDEX IF NOT EXISTS ix_up_identifier ON estate.usage_point (identifier);
CREATE INDEX IF NOT EXISTS ix_up_feeder     ON estate.usage_point (network_asset_id);

-- ─── L4 · Devices ────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS estate.meter (
    meter_id       UUID PRIMARY KEY,
    tenant_id      UUID NOT NULL REFERENCES estate.tenant(tenant_id),
    usage_point_id UUID NOT NULL REFERENCES estate.usage_point(usage_point_id),
    serial_number  TEXT NOT NULL,
    device_class   TEXT NOT NULL DEFAULT 'electricity',  -- electricity | gas | water | generic-iot
    generation     TEXT,                                 -- SMETS1 | SMETS2 | DLMS | ANSI-C12
    installed_at   TIMESTAMPTZ NOT NULL,
    removed_at     TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS ix_meter_up ON estate.meter (usage_point_id);

CREATE TABLE IF NOT EXISTS estate.reading_type (
    reading_type_id SERIAL PRIMARY KEY,
    cim_code        TEXT NOT NULL UNIQUE,
    uom             TEXT NOT NULL,        -- kWh | m3 | kVArh
    description     TEXT
);

CREATE TABLE IF NOT EXISTS estate.meter_register (
    register_id     UUID PRIMARY KEY,
    tenant_id       UUID NOT NULL REFERENCES estate.tenant(tenant_id),
    meter_id        UUID NOT NULL REFERENCES estate.meter(meter_id),
    reading_type_id INT  NOT NULL REFERENCES estate.reading_type(reading_type_id),
    direction       TEXT NOT NULL DEFAULT 'import'   -- import | export
);
CREATE INDEX IF NOT EXISTS ix_register_meter ON estate.meter_register (meter_id);

-- APPEND-ONLY. Never UPDATE, never DELETE. A 2026 proof must re-verify in 2029
-- against the key that was valid when the block was signed.
CREATE TABLE IF NOT EXISTS estate.meter_key (
    key_id          TEXT PRIMARY KEY,     -- matches TelemetryBlock.key_id
    tenant_id       UUID NOT NULL REFERENCES estate.tenant(tenant_id),
    meter_id        UUID NOT NULL REFERENCES estate.meter(meter_id),
    public_key_pem  TEXT NOT NULL,
    crypto_suite_id TEXT NOT NULL,        -- ECDSA-P256-SHA256-v1
    valid_from      TIMESTAMPTZ NOT NULL,
    valid_to        TIMESTAMPTZ           -- NULL = currently active
);
CREATE INDEX IF NOT EXISTS ix_key_meter ON estate.meter_key (meter_id, valid_from DESC);

-- ─── Market reference ────────────────────────────────────────────────────────
-- 46 on the short clock-change day, 50 on the long one. Never assume 48.
CREATE TABLE IF NOT EXISTS estate.settlement_calendar (
    market_code      VARCHAR(8) NOT NULL,
    settlement_date  DATE       NOT NULL,
    expected_periods SMALLINT   NOT NULL,
    interval_seconds INT        NOT NULL DEFAULT 1800,  -- 1800 GB | 900 EU | 300 AU
    PRIMARY KEY (market_code, settlement_date)
);

-- ─── The work queue the interface actually reads ─────────────────────────────
CREATE TABLE IF NOT EXISTS estate.omission_case (
    case_id         TEXT PRIMARY KEY,               -- DSP-2026-09842
    tenant_id       UUID NOT NULL REFERENCES estate.tenant(tenant_id),
    usage_point_id  UUID NOT NULL REFERENCES estate.usage_point(usage_point_id),
    settlement_date DATE NOT NULL,
    first_period    SMALLINT,
    last_period     SMALLINT,
    gap_count       SMALLINT NOT NULL,
    internal_gap    SMALLINT NOT NULL DEFAULT 0,
    boundary_gap    SMALLINT NOT NULL DEFAULT 0,
    eod_gap         SMALLINT NOT NULL DEFAULT 0,
    merkle_root     CHAR(64) NOT NULL,              -- points into the Iceberg evidence tier
    anchor_ref      TEXT,
    is_simulated_anchor BOOLEAN NOT NULL DEFAULT true,
    lifecycle_state TEXT NOT NULL DEFAULT 'new',    -- new | investigating | disputed
                                                    -- | reconciled | written_off
    owner_user_id   UUID,
    predicted_cause TEXT,                           -- outage | meter_fault | anomaly (model output)
    estimated_kwh   NUMERIC(12,3),                  -- ALWAYS an estimate, never mixed with measured
    notes           TEXT,
    extensions      JSONB NOT NULL DEFAULT '{}',    -- customer custom fields, never in the hash
    opened_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    closed_at       TIMESTAMPTZ,
    UNIQUE (tenant_id, usage_point_id, settlement_date)
);

-- This one index IS the Omission Register. "Open cases for my tenant, newest
-- first" must stay single-digit milliseconds regardless of corpus size.
CREATE INDEX IF NOT EXISTS ix_case_queue
    ON estate.omission_case (tenant_id, lifecycle_state, opened_at DESC);
CREATE INDEX IF NOT EXISTS ix_case_owner ON estate.omission_case (owner_user_id)
    WHERE closed_at IS NULL;
CREATE INDEX IF NOT EXISTS ix_case_ext   ON estate.omission_case USING GIN (extensions);
"""

# Tenant scope is a database guarantee, never an application promise.
# `app.tenant_id` is set per request from the verified JWT; a role can divide
# access within a tenant but nothing can cross the boundary.
RLS_SQL = """
DO $$
DECLARE t text;
BEGIN
    FOREACH t IN ARRAY ARRAY[
        'estate','service_location','network_asset','network_edge','usage_point',
        'meter','meter_register','meter_key','omission_case'
    ] LOOP
        EXECUTE format('ALTER TABLE estate.%I ENABLE ROW LEVEL SECURITY', t);
        EXECUTE format('ALTER TABLE estate.%I FORCE ROW LEVEL SECURITY', t);
        EXECUTE format(
            'DROP POLICY IF EXISTS tenant_isolation ON estate.%I', t);
        EXECUTE format(
            'CREATE POLICY tenant_isolation ON estate.%I USING '
            '(tenant_id = NULLIF(current_setting(''app.tenant_id'', true), '''')::uuid)', t);
    END LOOP;
END $$;
"""

SEED_REFERENCE_SQL = """
INSERT INTO estate.reading_type (cim_code, uom, description) VALUES
    ('0.0.0.1.1.1.12.0.0.0.0.0.0.0.0.3.72.0', 'kWh',   'Active energy import, half-hourly'),
    ('0.0.0.1.19.1.12.0.0.0.0.0.0.0.0.3.72.0','kWh',   'Active energy export, half-hourly'),
    ('0.0.0.1.1.1.63.0.0.0.0.0.0.0.0.3.73.0', 'kVArh', 'Reactive energy import'),
    ('0.0.0.1.1.1.12.0.0.0.0.0.0.0.0.3.42.0', 'm3',    'Gas volume, daily')
ON CONFLICT (cim_code) DO NOTHING;
"""


def _conn():
    """Reuse the existing connection helper so pooling and TLS stay consistent."""
    from auth_db import _get_conn
    return _get_conn()


def init_estate_schema(enable_rls: Optional[bool] = None) -> None:
    """Create the estate schema. Idempotent; safe to call on every startup."""
    if enable_rls is None:
        enable_rls = os.environ.get("ENVIRONMENT", "").strip().lower() != "development"

    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute(ESTATE_SCHEMA_SQL)
            cur.execute(SEED_REFERENCE_SQL)
            if enable_rls:
                cur.execute(RLS_SQL)
                logger.info("[estate_db] Row Level Security enabled on 9 tables")
            else:
                logger.warning(
                    "[estate_db] RLS NOT enabled (ENVIRONMENT=development). "
                    "Tenant isolation is application-level only."
                )
        conn.commit()
        logger.info("[estate_db] Estate schema initialised: 12 tables, reference data seeded")
    finally:
        conn.close()


def populate_settlement_calendar(market_code: str, year: int) -> int:
    """Fill a year of settlement dates.

    GB: 48 periods, except the two clock-change Sundays — 46 in March when the
    clocks go forward, 50 in October when they go back. Hard-coding 48 is the
    bug that surfaces on the last Sunday in October.
    """
    import calendar
    from datetime import date, timedelta

    def _last_sunday(y: int, m: int) -> date:
        last = calendar.monthrange(y, m)[1]
        d = date(y, m, last)
        return d - timedelta(days=(d.weekday() + 1) % 7)

    short_day = _last_sunday(year, 3)    # clocks forward → 46 periods
    long_day = _last_sunday(year, 10)    # clocks back    → 50 periods

    rows, day = [], date(year, 1, 1)
    while day.year == year:
        periods = 46 if day == short_day else 50 if day == long_day else 48
        rows.append((market_code, day, periods, 1800))
        day += timedelta(days=1)

    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO estate.settlement_calendar "
                "(market_code, settlement_date, expected_periods, interval_seconds) "
                "VALUES (%s, %s, %s, %s) ON CONFLICT DO NOTHING",
                rows,
            )
        conn.commit()
        logger.info(
            "[estate_db] Calendar seeded for %s %d (%s=46, %s=50)",
            market_code, year, short_day, long_day,
        )
        return len(rows)
    finally:
        conn.close()


def seed_synthetic_estate(tenant_name: str = "Demo Energy", meter_count: int = 500) -> dict:
    """Create a synthetic estate with a real network topology.

    Builds one primary substation feeding four distribution substations, each
    with three LV feeders, and distributes meters across them. The topology is
    what makes gap clustering meaningful — forty meters on one feeder losing the
    same periods is an outage; one meter alone is worth investigating.
    """
    import hashlib
    import uuid
    from datetime import datetime, timezone

    t_id = uuid.uuid4()
    e_id = uuid.uuid4()
    now = datetime.now(timezone.utc)
    created = {"tenant_id": str(t_id), "estate_id": str(e_id),
               "feeders": 0, "usage_points": 0, "meters": 0}

    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO estate.tenant (tenant_id, name, tenant_type) VALUES (%s,%s,%s)",
                (str(t_id), tenant_name, "supplier"))
            cur.execute(
                "INSERT INTO estate.estate (estate_id, tenant_id, name, market_code, "
                "expected_sp_per_day) VALUES (%s,%s,%s,%s,%s)",
                (str(e_id), str(t_id), f"{tenant_name} — UK North", "GB", 48))

            primary = uuid.uuid4()
            cur.execute(
                "INSERT INTO estate.network_asset (network_asset_id, tenant_id, asset_type, "
                "cim_class, name, voltage_kv, gsp_group) VALUES (%s,%s,%s,%s,%s,%s,%s)",
                (str(primary), str(t_id), "primary", "Substation",
                 "Northgate Primary", 33.0, "_A"))

            feeders = []
            for d in range(4):
                dist = uuid.uuid4()
                cur.execute(
                    "INSERT INTO estate.network_asset (network_asset_id, tenant_id, asset_type, "
                    "cim_class, name, voltage_kv, gsp_group) VALUES (%s,%s,%s,%s,%s,%s,%s)",
                    (str(dist), str(t_id), "distribution", "Substation",
                     f"Northgate DS-{d+1}", 11.0, "_A"))
                cur.execute(
                    "INSERT INTO estate.network_edge (tenant_id, parent_id, child_id, relation, "
                    "valid_from) VALUES (%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                    (str(t_id), str(primary), str(dist), "SUPPLIES", now.date()))
                for f in range(3):
                    lv = uuid.uuid4()
                    cur.execute(
                        "INSERT INTO estate.network_asset (network_asset_id, tenant_id, "
                        "asset_type, cim_class, name, voltage_kv, gsp_group) "
                        "VALUES (%s,%s,%s,%s,%s,%s,%s)",
                        (str(lv), str(t_id), "lv_feeder", "ACLineSegment",
                         f"DS-{d+1} Feeder {f+1}", 0.4, "_A"))
                    cur.execute(
                        "INSERT INTO estate.network_edge (tenant_id, parent_id, child_id, "
                        "relation, valid_from) VALUES (%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                        (str(t_id), str(dist), str(lv), "SUPPLIES", now.date()))
                    feeders.append(lv)
            created["feeders"] = len(feeders)

            cur.execute("SELECT reading_type_id FROM estate.reading_type "
                        "WHERE uom='kWh' ORDER BY reading_type_id LIMIT 1")
            rt_id = cur.fetchone()[0]

            for i in range(meter_count):
                mpan = f"10{(1000000000 + i):011d}"          # 13 digits
                bucket = int(hashlib.sha256(mpan.encode()).hexdigest()[:8], 16) % 16
                up_id, m_id, loc_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
                feeder = feeders[i % len(feeders)]

                cur.execute(
                    "INSERT INTO estate.service_location (service_location_id, tenant_id, "
                    "address_line, postcode) VALUES (%s,%s,%s,%s)",
                    (str(loc_id), str(t_id), f"{i+1} Example Street", "NE1 1AA"))
                cur.execute(
                    "INSERT INTO estate.usage_point (usage_point_id, tenant_id, estate_id, "
                    "identifier, identifier_scheme, identifier_bucket, service_location_id, "
                    "network_asset_id, profile_class, gsp_group, energised_from) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                    (str(up_id), str(t_id), str(e_id), mpan, "gb-mpan", bucket,
                     str(loc_id), str(feeder), "03", "_A", now.date()))
                cur.execute(
                    "INSERT INTO estate.meter (meter_id, tenant_id, usage_point_id, "
                    "serial_number, device_class, generation, installed_at) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s)",
                    (str(m_id), str(t_id), str(up_id), f"SM{i:08d}",
                     "electricity", "SMETS2", now))
                cur.execute(
                    "INSERT INTO estate.meter_register (register_id, tenant_id, meter_id, "
                    "reading_type_id, direction) VALUES (%s,%s,%s,%s,%s)",
                    (str(uuid.uuid4()), str(t_id), str(m_id), rt_id, "import"))

            created["usage_points"] = meter_count
            created["meters"] = meter_count
        conn.commit()
        logger.info("[estate_db] Synthetic estate: %s", created)
        return created
    finally:
        conn.close()
