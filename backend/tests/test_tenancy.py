"""
Regression tests for tenancy.py -- the namespace isolation mechanism
multi-tenant isolation is built on. No database/catalog needed; these
test the pure string-scoping logic directly.
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import tenancy

TENANT_A = "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
TENANT_B = "ffffffff-1111-2222-3333-444444444444"


def test_same_display_name_maps_to_different_real_namespaces():
    scoped_a = tenancy.scope_namespace(TENANT_A, "default")
    scoped_b = tenancy.scope_namespace(TENANT_B, "default")
    assert scoped_a != scoped_b


def test_tenant_can_unscope_their_own_namespace():
    scoped = tenancy.scope_namespace(TENANT_A, "default")
    assert tenancy.unscope_namespace(TENANT_A, scoped) == "default"


def test_tenant_cannot_unscope_another_tenants_namespace():
    """The actual isolation boundary: a namespace belonging to a different
    tenant must never be revealed, not even by name."""
    scoped_a = tenancy.scope_namespace(TENANT_A, "default")
    assert tenancy.unscope_namespace(TENANT_B, scoped_a) is None


def test_filtering_a_shared_catalog_isolates_to_one_tenant():
    all_namespaces = [
        tenancy.scope_namespace(TENANT_A, "default"),
        tenancy.scope_namespace(TENANT_A, "finance"),
        tenancy.scope_namespace(TENANT_B, "default"),
        "some_unrelated_namespace",
    ]
    visible_to_a = tenancy.filter_and_unscope_namespaces(TENANT_A, all_namespaces)
    assert set(visible_to_a) == {"default", "finance"}


def test_wildcard_passes_through_unscoped():
    assert tenancy.scope_namespace(TENANT_A, "*") == "*"


def test_double_scoping_is_idempotent():
    """Re-scoping an already-scoped namespace must not double-prefix it --
    guards against accidental double-translation if a value round-trips
    through scope_namespace() twice."""
    once = tenancy.scope_namespace(TENANT_A, "default")
    twice = tenancy.scope_namespace(TENANT_A, once)
    assert once == twice


def test_get_current_tenant_id_requires_authenticated_user():
    import pytest
    with pytest.raises(ValueError):
        tenancy.get_current_tenant_id({})  # no "sub" claim present


def test_get_current_tenant_id_never_trusts_client_supplied_fields():
    """tenant_id must come only from the JWT's own "sub" claim -- never
    from a field an attacker could put in the request body."""
    user = {"sub": "real-user-id-from-jwt", "tenant_id": "attacker-supplied-value"}
    assert tenancy.get_current_tenant_id(user) == "real-user-id-from-jwt"
