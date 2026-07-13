# Copyright (c) 2025 Meldra AI Ltd. All rights reserved.
# This software is proprietary and confidential. Unauthorised use is prohibited.
"""
oidc.py — Generic OpenID Connect SSO.

Works with any real OIDC-compliant identity provider (Okta, Azure AD /
Microsoft Entra ID, Google Workspace, Auth0, Keycloak, ...) via the
standard `/.well-known/openid-configuration` discovery document, rather
than hardcoding endpoint URLs per vendor.

Config comes entirely from environment variables:
  OIDC_ISSUER_URL      e.g. https://your-tenant.okta.com/oauth2/default
  OIDC_CLIENT_ID
  OIDC_CLIENT_SECRET
  OIDC_REDIRECT_URI    must exactly match what's registered with the IdP,
                        e.g. https://api.meldra.ai/auth/sso/callback
  OIDC_PROVIDER_NAME   display name for the "Sign in with X" button (optional)

Until all four required variables are set, is_configured() is False and
the /auth/sso/* endpoints in api/main.py return 501 rather than attempting
a broken redirect — there's no fake IdP to fall back to here, unlike the
AGE/query-engine fallbacks elsewhere in this codebase.
"""

from __future__ import annotations

import os
import time
import secrets as _secrets
from typing import Any, Dict
from urllib.parse import urlencode

import requests
from jose import jwt as jose_jwt

_discovery_cache: Dict[str, Any] = {}
_discovery_cache_at: float = 0.0
_DISCOVERY_TTL_SECONDS = 3600

# In-memory CSRF state store: state -> expiry timestamp. Fine for a
# single-process deployment; a multi-replica deployment behind a load
# balancer with no session affinity would need this in Redis/Postgres
# instead of process memory — noted here rather than silently working
# only some of the time once this codebase actually runs replicas > 1
# (see kubernetes/deployment.yaml's HPA, which now does exactly that).
_pending_states: Dict[str, float] = {}
_STATE_TTL_SECONDS = 600

REQUIRED_ENV_VARS = ("OIDC_ISSUER_URL", "OIDC_CLIENT_ID", "OIDC_CLIENT_SECRET", "OIDC_REDIRECT_URI")


def is_configured() -> bool:
    return all(os.environ.get(v) for v in REQUIRED_ENV_VARS)


def provider_name() -> str:
    return os.environ.get("OIDC_PROVIDER_NAME", "SSO")


def _discovery() -> Dict[str, Any]:
    """Fetch (and cache) the IdP's OIDC discovery document."""
    global _discovery_cache, _discovery_cache_at
    if _discovery_cache and (time.time() - _discovery_cache_at) < _DISCOVERY_TTL_SECONDS:
        return _discovery_cache

    issuer = os.environ["OIDC_ISSUER_URL"].rstrip("/")
    resp = requests.get(f"{issuer}/.well-known/openid-configuration", timeout=10)
    resp.raise_for_status()
    _discovery_cache = resp.json()
    _discovery_cache_at = time.time()
    return _discovery_cache


def _cleanup_expired_states() -> None:
    now = time.time()
    for s in [s for s, exp in _pending_states.items() if exp < now]:
        _pending_states.pop(s, None)


def build_authorization_url() -> str:
    """Generates a fresh CSRF `state`, remembers it, and returns the URL to
    redirect the browser to at the IdP's login page."""
    if not is_configured():
        raise RuntimeError(
            "OIDC is not configured — set OIDC_ISSUER_URL, OIDC_CLIENT_ID, "
            "OIDC_CLIENT_SECRET and OIDC_REDIRECT_URI."
        )

    _cleanup_expired_states()
    state = _secrets.token_urlsafe(24)
    _pending_states[state] = time.time() + _STATE_TTL_SECONDS

    discovery = _discovery()
    params = {
        "client_id": os.environ["OIDC_CLIENT_ID"],
        "redirect_uri": os.environ["OIDC_REDIRECT_URI"],
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
    }
    return f"{discovery['authorization_endpoint']}?{urlencode(params)}"


def consume_state(state: str) -> bool:
    """True (and forgets it) if `state` was one we issued and hasn't
    expired — guards the callback against CSRF and replay."""
    _cleanup_expired_states()
    return _pending_states.pop(state, None) is not None


def exchange_code_for_claims(code: str) -> Dict[str, Any]:
    """
    Exchanges an authorization `code` for tokens at the IdP's token
    endpoint, then verifies the returned id_token's signature against the
    IdP's published JWKS (matching the correct signing key by `kid`) and
    checks issuer + audience + expiry — so a malicious redirect can't hand
    back a token this backend would trust blindly. Returns the verified
    claims (sub, email, name, ...).
    """
    discovery = _discovery()

    token_resp = requests.post(
        discovery["token_endpoint"],
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": os.environ["OIDC_REDIRECT_URI"],
            "client_id": os.environ["OIDC_CLIENT_ID"],
            "client_secret": os.environ["OIDC_CLIENT_SECRET"],
        },
        timeout=10,
    )
    token_resp.raise_for_status()
    id_token = token_resp.json().get("id_token")
    if not id_token:
        raise ValueError("IdP token response did not include an id_token.")

    return verify_id_token(id_token, discovery)


def verify_id_token(id_token: str, discovery: Dict[str, Any] | None = None) -> Dict[str, Any]:
    """Verifies an id_token's signature + issuer/audience/expiry against
    the IdP's JWKS. Split out from exchange_code_for_claims so it's
    independently testable against a locally-generated token/JWKS pair."""
    discovery = discovery or _discovery()
    jwks = requests.get(discovery["jwks_uri"], timeout=10).json()

    unverified_header = jose_jwt.get_unverified_header(id_token)
    key = next((k for k in jwks["keys"] if k.get("kid") == unverified_header.get("kid")), None)
    if key is None:
        raise ValueError("Could not find a matching signing key in the IdP's JWKS for this id_token.")

    return jose_jwt.decode(
        id_token,
        key,
        algorithms=[unverified_header.get("alg", "RS256")],
        audience=os.environ["OIDC_CLIENT_ID"],
        issuer=discovery.get("issuer", os.environ.get("OIDC_ISSUER_URL")),
    )
