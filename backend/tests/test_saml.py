# Copyright (c) 2025-2026 Meldra AI Ltd. All rights reserved.
"""
tests/test_saml.py — Verification for SAML 2.0 Service Provider functionality.
"""

import base64
import os
import pytest
import saml


@pytest.fixture(autouse=True)
def saml_env(monkeypatch):
    monkeypatch.setenv("SAML_SP_ENTITY_ID", "https://api.meldra.ai/auth/saml/metadata")
    monkeypatch.setenv("SAML_SP_ACS_URL", "https://api.meldra.ai/auth/saml/acs")
    monkeypatch.setenv("SAML_IDP_SSO_URL", "https://idp.example.com/sso")
    monkeypatch.setenv("SAML_PROVIDER_NAME", "Okta Enterprise")


def test_saml_configuration_detection():
    assert saml.is_configured() is True
    assert saml.provider_name() == "Okta Enterprise"


def test_generate_sp_metadata():
    metadata = saml.generate_sp_metadata()
    assert "EntityDescriptor" in metadata
    assert "https://api.meldra.ai/auth/saml/metadata" in metadata
    assert "https://api.meldra.ai/auth/saml/acs" in metadata


def test_build_authn_request_url():
    url = saml.build_authn_request_url(relay_state="custom_state_123")
    assert url.startswith("https://idp.example.com/sso")
    assert "SAMLRequest=" in url
    assert "RelayState=custom_state_123" in url
    assert saml.validate_relay_state("custom_state_123") is True
    # Verify replay protection: state consumed once
    assert saml.validate_relay_state("custom_state_123") is False


def test_parse_saml_response_valid():
    sample_xml = """<samlp:Response xmlns:samlp="urn:oasis:names:tc:SAML:2.0:protocol"
                                xmlns:saml="urn:oasis:names:tc:SAML:2.0:assertion"
                                ID="_resp123" Version="2.0" IssueInstant="2026-09-09T12:00:00Z">
        <samlp:Status>
            <samlp:StatusCode Value="urn:oasis:names:tc:SAML:2.0:status:Success"/>
        </samlp:Status>
        <saml:Assertion ID="_assert123" Version="2.0" IssueInstant="2026-09-09T12:00:00Z">
            <saml:Issuer>https://idp.example.com/sso</saml:Issuer>
            <saml:Subject>
                <saml:NameID Format="urn:oasis:names:tc:SAML:1.1:nameid-format:emailAddress">
                    alice@enterprise.com
                </saml:NameID>
            </saml:Subject>
            <saml:Conditions NotBefore="2026-09-09T11:55:00Z" NotOnOrAfter="2026-09-09T12:05:00Z">
                <saml:AudienceRestriction>
                    <saml:Audience>https://api.meldra.ai/auth/saml/metadata</saml:Audience>
                </saml:AudienceRestriction>
            </saml:Conditions>
            <saml:AttributeStatement>
                <saml:Attribute Name="email">
                    <saml:AttributeValue>alice@enterprise.com</saml:AttributeValue>
                </saml:Attribute>
                <saml:Attribute Name="name">
                    <saml:AttributeValue>Alice Johnson</saml:AttributeValue>
                </saml:Attribute>
                <saml:Attribute Name="role">
                    <saml:AttributeValue>Admin</saml:AttributeValue>
                </saml:Attribute>
            </saml:AttributeStatement>
        </saml:Assertion>
    </samlp:Response>"""

    b64_xml = base64.b64encode(sample_xml.encode("utf-8")).decode("ascii")
    claims = saml.parse_saml_response(b64_xml)

    assert claims["email"] == "alice@enterprise.com"
    assert claims["name"] == "Alice Johnson"
    assert "Admin" in claims["roles"]
