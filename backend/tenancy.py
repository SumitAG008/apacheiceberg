# Copyright (c) 2025 Meldra AI Ltd. All rights reserved.
"""
tenancy.py — Multi-tenant namespace isolation.

Model: one tenant = one registered account (tenant_id = the user's own UUID
from the JWT). No team/org/invite system yet, so this is the simplest
correct unit -- it can grow into multi-user tenants later without changing
the isolation mechanism itself.

Isolation approach: shared Iceberg catalog, shared S3 warehouse, but every
namespace a client can see or write to is silently prefixed with the
tenant's ID before it ever reaches the catalog. The UI and API responses
show "default", "finance", etc.; the catalog actually stores
"t_<tenant_id>__default". A tenant can never list, reference, or guess
their way into another tenant's namespace, because unscope_namespace()
refuses to strip a prefix that doesn't belong to the caller.

This module does the translation at the API boundary — endpoints call
scope_namespace() on every client-supplied namespace before touching the
catalog, and unscope_namespace() on every namespace read back before
returning it to the client. Business logic (MeldraCatalog, tools.py, the
query engine) never needs to know tenancy exists; it just operates on
whatever (already-scoped) namespace string it's given, exactly as before.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

_PREFIX_SEP = "__"


def _clean_tenant_fragment(tenant_id: str) -> str:
    """Iceberg/Glue namespace names are restrictive about characters; strip
    everything but alphanumerics so a UUID like 'a1b2-c3d4' becomes a safe
    fragment."""
    return re.sub(r"[^a-zA-Z0-9]", "", tenant_id).lower()


def get_current_tenant_id(user: Dict[str, Any]) -> str:
    """
    The tenant a request belongs to, derived ONLY from the authenticated
    JWT payload (`user["sub"]`, the user id) — never from a client-supplied
    field. One account = one tenant in this model.
    """
    tenant = user.get("sub")
    if not tenant:
        raise ValueError("Cannot determine tenant: no authenticated user id present.")
    return tenant


def tenant_prefix(tenant_id: str) -> str:
    return f"t_{_clean_tenant_fragment(tenant_id)}{_PREFIX_SEP}"


def scope_namespace(tenant_id: str, namespace: str) -> str:
    """Translate a client-facing namespace (e.g. 'default') into the real,
    tenant-scoped catalog namespace (e.g. 't_a1b2c3d4__default')."""
    if namespace == "*":
        # Wildcard is meaningful within RBAC policy scoping, not as a real
        # catalog namespace — pass through unscoped, callers must not use
        # "*" as an actual namespace to create/query.
        return "*"
    prefix = tenant_prefix(tenant_id)
    if namespace.startswith(prefix):
        # Already scoped (e.g. re-scoping a value that round-tripped) — avoid
        # double-prefixing.
        return namespace
    return f"{prefix}{namespace}"


def unscope_namespace(tenant_id: str, full_namespace: str) -> Optional[str]:
    """
    Strip this tenant's prefix off a real catalog namespace, returning the
    client-facing name (e.g. 't_a1b2c3d4__default' -> 'default'). Returns
    None if `full_namespace` does not belong to this tenant at all — this
    is the actual isolation boundary: a namespace belonging to a different
    tenant is never revealed, not even by name.
    """
    prefix = tenant_prefix(tenant_id)
    if not full_namespace.startswith(prefix):
        return None
    return full_namespace[len(prefix):]


def filter_and_unscope_namespaces(tenant_id: str, all_namespaces: List[str]) -> List[str]:
    """Given every namespace in the shared catalog, return only the ones
    belonging to this tenant, with the prefix stripped for display."""
    result = []
    for ns in all_namespaces:
        display = unscope_namespace(tenant_id, ns)
        if display is not None:
            result.append(display)
    return result
