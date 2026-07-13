# Copyright (c) 2025 Meldra AI Ltd. All rights reserved.
"""
roles.py — canonical persona registry for the platform.

Every endpoint that gates on role imports its allow-set from here instead of
hardcoding a role list inline, so the personas below are the single source
of truth for "who can do what." `user_role` on auth.users stays a free-text
column (see auth_db.py) — this module is what gives those strings meaning.

Four roles (Admin, Data Engineer, Data Architect, Business Analyst) existed
before and keep their exact prior behaviour. Consultant, CIO, COO and Viewer
are new personas added to cover an Architect (= Data Architect)/Consultant/
Business user/CIO/COO/non-technical-viewer spread:

  - CIO / COO / Viewer are "dashboard-only": they can browse the catalog and
    Observability metrics, but cannot submit ad-hoc queries or ingest data.
    This is enforced at the endpoint layer (see api/main.py), not just by
    hiding buttons in the UI.
  - Consultant is scoped, not dashboard-only: they CAN query, but are
    deny-by-default on every namespace (see the wildcard '__TABLE__' deny
    policy seeded in auth_db.py) until an Admin grants an explicit 'allow'
    on specific namespaces — see rbac_utils.check_table_access.
"""

from __future__ import annotations

ROLE_ADMIN = "Admin"
ROLE_DATA_ENGINEER = "Data Engineer"
ROLE_DATA_ARCHITECT = "Data Architect"
ROLE_BUSINESS_ANALYST = "Business Analyst"
ROLE_CONSULTANT = "Consultant"
ROLE_CIO = "CIO"
ROLE_COO = "COO"
ROLE_VIEWER = "Viewer"

ALL_ROLES = [
    ROLE_ADMIN,
    ROLE_DATA_ENGINEER,
    ROLE_DATA_ARCHITECT,
    ROLE_BUSINESS_ANALYST,
    ROLE_CONSULTANT,
    ROLE_CIO,
    ROLE_COO,
    ROLE_VIEWER,
]

ROLE_DESCRIPTIONS = {
    ROLE_ADMIN: "Full platform access — manages roles, policies and every layer.",
    ROLE_DATA_ENGINEER: "Builds and operates pipelines. Read/write Bronze & Silver, read Gold, runs Python extraction.",
    ROLE_DATA_ARCHITECT: "Owns schema and namespace standards. Approves schema changes and namespace lifecycle.",
    ROLE_BUSINESS_ANALYST: "Gold-tier self-service. Queries certified tables; PII masked automatically.",
    ROLE_CONSULTANT: "External/time-boxed. No access to any namespace until an Admin explicitly grants one.",
    ROLE_CIO: "Executive. Dashboard-only: cost, trust, compliance and adoption metrics — no ad-hoc queries.",
    ROLE_COO: "Executive. Dashboard-only: pipeline health, run history and SLA risk — no ad-hoc queries.",
    ROLE_VIEWER: "Non-technical. Dashboard-only: catalog browsing and Observability, nothing else.",
}

# Capability sets — every role-gated endpoint should check membership here
# instead of hardcoding a role list, so this file stays the single place
# personas are defined.
CAN_RUN_PYTHON = {ROLE_ADMIN, ROLE_DATA_ENGINEER}
CAN_MANAGE_SCHEMA = {ROLE_ADMIN, ROLE_DATA_ARCHITECT}
CAN_MANAGE_RBAC = {ROLE_ADMIN}
CAN_INGEST = {ROLE_ADMIN, ROLE_DATA_ENGINEER, ROLE_DATA_ARCHITECT, ROLE_BUSINESS_ANALYST}

# Roles that get a dashboard (catalog browse + Observability) but cannot
# submit ad-hoc queries or ingest data, enforced at the endpoint layer.
DASHBOARD_ONLY_ROLES = {ROLE_CIO, ROLE_COO, ROLE_VIEWER}
