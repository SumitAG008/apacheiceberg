# Copyright (c) 2025-2026 Meldra AI Ltd. All rights reserved.
# This software is proprietary and confidential. Unauthorised use is prohibited.
"""
saml.py — Enterprise SAML 2.0 Service Provider (SP) Integration.

Enables Single Sign-On (SSO) for enterprise and government deployments using
the SAML 2.0 Web Browser SSO profile (SP-Initiated and IdP-Initiated).
Works alongside oidc.py to satisfy enterprise IT policies requiring SAML 2.0
(e.g., Azure AD / Entra ID, Okta, Ping Identity, Keycloak, ADFS, Shibboleth).

Configuration (environment variables):
  SAML_SP_ENTITY_ID     SP entity ID, e.g. https://api.meldra.ai/auth/saml/metadata
  SAML_SP_ACS_URL       Assertion Consumer Service URL, e.g. https://api.meldra.ai/auth/saml/acs
  SAML_IDP_SSO_URL      IdP Single Sign-On service URL (HTTP-Redirect or HTTP-POST)
  SAML_IDP_ENTITY_ID    IdP entity ID / Issuer
  SAML_IDP_CERT         X.509 public certificate of IdP (base64 PEM string or raw DER base64)
  SAML_PROVIDER_NAME    Display name for login UI, e.g. "Enterprise SAML"
"""

from __future__ import annotations

import base64
import logging
import os
import secrets
import time
import urllib.parse
import zlib
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import xml.etree.ElementTree as ET

logger = logging.getLogger(__name__)

# SAML 2.0 XML Namespaces
NS = {
    "samlp": "urn:oasis:names:tc:SAML:2.0:protocol",
    "saml": "urn:oasis:names:tc:SAML:2.0:assertion",
    "ds": "http://www.w3.org/2000/09/xmldsig#",
    "md": "urn:oasis:names:tc:SAML:2.0:metadata",
}

REQUIRED_ENV_VARS = ("SAML_SP_ENTITY_ID", "SAML_SP_ACS_URL", "SAML_IDP_SSO_URL")

# In-memory relay_state cache (relay_state -> expiry timestamp)
_pending_states: Dict[str, float] = {}
_STATE_TTL_SECONDS = 600


def is_configured() -> bool:
    """Return True if the minimum required SAML environment variables are configured."""
    return all(os.environ.get(v) for v in REQUIRED_ENV_VARS)


def provider_name() -> str:
    """Return user-friendly provider display name."""
    return os.environ.get("SAML_PROVIDER_NAME", "Enterprise SAML")


def _clean_expired_states() -> None:
    now = time.time()
    for s in [k for k, exp in _pending_states.items() if exp < now]:
        _pending_states.pop(s, None)


def generate_sp_metadata() -> str:
    """
    Generate SAML 2.0 EntityDescriptor metadata XML for Service Provider registration.
    Enterprises import this XML into their IdP (Okta, Entra ID, Ping) to configure Meldra.
    """
    sp_entity_id = os.environ.get("SAML_SP_ENTITY_ID", "https://api.meldra.ai/auth/saml/metadata")
    acs_url = os.environ.get("SAML_SP_ACS_URL", "https://api.meldra.ai/auth/saml/acs")

    metadata = f"""<?xml version="1.0" encoding="UTF-8"?>
<md:EntityDescriptor xmlns:md="urn:oasis:names:tc:SAML:2.0:metadata"
                     entityID="{sp_entity_id}">
    <md:SPSSODescriptor AuthnRequestsSigned="false"
                        WantAssertionsSigned="true"
                        protocolSupportEnumeration="urn:oasis:names:tc:SAML:2.0:protocol">
        <md:NameIDFormat>urn:oasis:names:tc:SAML:1.1:nameid-format:emailAddress</md:NameIDFormat>
        <md:NameIDFormat>urn:oasis:names:tc:SAML:2.0:nameid-format:persistent</md:NameIDFormat>
        <md:NameIDFormat>urn:oasis:names:tc:SAML:2.0:nameid-format:transient</md:NameIDFormat>
        <md:AssertionConsumerService Binding="urn:oasis:names:tc:SAML:2.0:bindings:HTTP-POST"
                                     Location="{acs_url}"
                                     index="1"
                                     isDefault="true"/>
    </md:SPSSODescriptor>
</md:EntityDescriptor>"""
    return metadata.strip()


def build_authn_request_url(relay_state: Optional[str] = None) -> str:
    """
    Builds a SAML 2.0 AuthnRequest XML, compresses with Deflate, base64 encodes it,
    and constructs the HTTP-Redirect binding URL.
    """
    if not is_configured():
        raise RuntimeError("SAML is not configured. Set SAML_SP_ENTITY_ID, SAML_SP_ACS_URL, SAML_IDP_SSO_URL.")

    _clean_expired_states()
    sp_entity_id = os.environ["SAML_SP_ENTITY_ID"]
    acs_url = os.environ["SAML_SP_ACS_URL"]
    idp_sso_url = os.environ["SAML_IDP_SSO_URL"]

    request_id = "_" + secrets.token_hex(16)
    issue_instant = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    if not relay_state:
        relay_state = secrets.token_urlsafe(24)
    _pending_states[relay_state] = time.time() + _STATE_TTL_SECONDS

    authn_request_xml = f"""<samlp:AuthnRequest xmlns:samlp="urn:oasis:names:tc:SAML:2.0:protocol"
                    xmlns:saml="urn:oasis:names:tc:SAML:2.0:assertion"
                    ID="{request_id}"
                    Version="2.0"
                    IssueInstant="{issue_instant}"
                    Destination="{idp_sso_url}"
                    ProtocolBinding="urn:oasis:names:tc:SAML:2.0:bindings:HTTP-POST"
                    AssertionConsumerServiceURL="{acs_url}">
    <saml:Issuer>{sp_entity_id}</saml:Issuer>
    <samlp:NameIDPolicy Format="urn:oasis:names:tc:SAML:1.1:nameid-format:emailAddress"
                        AllowCreate="true"/>
</samlp:AuthnRequest>"""

    # Deflate compress without headers (RFC 1951)
    compressor = zlib.compressobj(zlib.Z_DEFAULT_COMPRESSION, zlib.DEFLATED, -15)
    deflated = compressor.compress(authn_request_xml.encode("utf-8")) + compressor.flush()
    saml_request_b64 = base64.b64encode(deflated).decode("ascii")

    params = {
        "SAMLRequest": saml_request_b64,
        "RelayState": relay_state,
    }
    delim = "&" if "?" in idp_sso_url else "?"
    return f"{idp_sso_url}{delim}{urllib.parse.urlencode(params)}"


def validate_relay_state(relay_state: str) -> bool:
    """Validate and consume CSRF relay_state."""
    _clean_expired_states()
    exp = _pending_states.pop(relay_state, None)
    if exp is None:
        return False
    return exp >= time.time()


def parse_saml_response(saml_response_b64: str) -> Dict[str, Any]:
    """
    Parse and validate SAMLResponse POST payload.

    Extracts:
      - Subject NameID (email/identity)
      - SAML attributes (email, name, roles, groups)
      - IssueInstant, Audience, and SessionIndex
    """
    try:
        xml_bytes = base64.b64decode(saml_response_b64)
    except Exception as e:
        raise ValueError(f"Failed to base64 decode SAMLResponse: {e}") from e

    # Defend against XXE attacks: forbid DTD / external entities
    if b"<!DOCTYPE" in xml_bytes or b"<!ENTITY" in xml_bytes:
        raise ValueError("SAML XML containing DTD or ENTITY declarations is rejected for security.")

    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError as e:
        raise ValueError(f"Malformed SAML XML: {e}") from e

    # 1. Validate StatusCode
    status_code_elem = root.find(".//samlp:Status/samlp:StatusCode", NS)
    if status_code_elem is not None:
        val = status_code_elem.attrib.get("Value", "")
        if not val.endswith("Success"):
            status_msg = root.find(".//samlp:Status/samlp:StatusMessage", NS)
            detail = status_msg.text if status_msg is not None else val
            raise ValueError(f"SAML IdP returned non-success status: {detail}")

    # 2. Extract Assertion
    assertion = root.find(".//saml:Assertion", NS)
    if assertion is None:
        raise ValueError("No SAML Assertion found in response")

    # 3. Verify AudienceRestriction if SP Entity ID is configured
    sp_entity_id = os.environ.get("SAML_SP_ENTITY_ID")
    if sp_entity_id:
        audience_elems = assertion.findall(".//saml:Conditions/saml:AudienceRestriction/saml:Audience", NS)
        if audience_elems:
            audiences = [a.text.strip() for a in audience_elems if a.text]
            if sp_entity_id not in audiences:
                logger.warning(
                    "[SAML] Audience mismatch: expected %s, found %s",
                    sp_entity_id, audiences,
                )

    # 4. Extract NameID (Subject)
    name_id_elem = assertion.find(".//saml:Subject/saml:NameID", NS)
    name_id = name_id_elem.text.strip() if name_id_elem is not None and name_id_elem.text else None

    # 5. Extract Attributes
    attributes: Dict[str, Any] = {}
    attr_elems = assertion.findall(".//saml:AttributeStatement/saml:Attribute", NS)
    for attr in attr_elems:
        attr_name = attr.attrib.get("Name", "")
        friendly_name = attr.attrib.get("FriendlyName", "")
        key = friendly_name or attr_name
        values = [v.text.strip() for v in attr.findall("saml:AttributeValue", NS) if v.text]
        if len(values) == 1:
            attributes[key] = values[0]
            attributes[attr_name] = values[0]
        elif len(values) > 1:
            attributes[key] = values
            attributes[attr_name] = values

    # Determine resolved email address
    resolved_email = (
        attributes.get("email")
        or attributes.get("mail")
        or attributes.get("User.Email")
        or attributes.get("http://schemas.xmlsoap.org/ws/2005/05/identity/claims/emailaddress")
        or name_id
    )
    if not resolved_email or "@" not in resolved_email:
        raise ValueError("Could not extract a valid email from SAML assertion")

    roles = (
        attributes.get("role")
        or attributes.get("roles")
        or attributes.get("groups")
        or attributes.get("http://schemas.microsoft.com/ws/2008/06/identity/claims/role")
    )
    if isinstance(roles, str):
        role_list = [roles]
    elif isinstance(roles, (list, tuple)):
        role_list = list(roles)
    else:
        role_list = []

    return {
        "email": resolved_email.lower(),
        "name_id": name_id,
        "name": attributes.get("name") or attributes.get("displayName") or resolved_email.split("@")[0],
        "roles": role_list,
        "attributes": attributes,
        "issue_instant": assertion.attrib.get("IssueInstant"),
    }
