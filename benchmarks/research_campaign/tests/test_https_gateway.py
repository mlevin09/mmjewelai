"""Offline protocol/auth tests. Synthetic issuer/keys are NEVER a live OAuth proof."""

import json
import ssl
import time
from dataclasses import replace
from unittest.mock import MagicMock

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from starlette.testclient import TestClient

from jewelai_research.contracts import TARGET
from jewelai_research.https_auth import (
    STATUS_SCOPE,
    ConfigurationError,
    OAuthConfig,
    OAuthTokenVerifier,
    _NoRedirect,
    public_json,
    validate_authorization_server,
)
from jewelai_research.https_gateway import ComputeStatus, StatusUnavailable, create_app


@pytest.fixture
def oauth():
    config = OAuthConfig(
        resource_url="https://mcp.example.test/mcp",
        issuer_url="https://issuer.example.test/",
        discovery_url="https://issuer.example.test/.well-known/openid-configuration",
        client_id="synthetic-registered-client",
        allowed_subjects=("synthetic-owner",),
        callback_url="https://chatgpt.com/connector_platform_oauth_redirect",
    )
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public = jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key(), as_dict=True)
    public.update(kid="synthetic-key", alg="RS256", use="sig")
    metadata = {
        "issuer": config.issuer_url,
        "authorization_endpoint": config.issuer_url + "authorize",
        "token_endpoint": config.issuer_url + "token",
        "jwks_uri": config.issuer_url + "jwks",
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code"],
        "code_challenge_methods_supported": ["S256"],
        "authorization_response_iss_parameter_supported": True,
    }
    fetches = []

    def fetch(url):
        fetches.append(url)
        if url == config.discovery_url:
            return dict(metadata)
        assert url == metadata["jwks_uri"]
        return {"keys": [dict(public)]}

    def token(**overrides):
        claims = {
            "iss": config.issuer_url,
            "aud": config.resource_url,
            "sub": config.allowed_subjects[0],
            "client_id": config.client_id,
            "iat": int(time.time()),
            "exp": int(time.time()) + 60,
            "scope": STATUS_SCOPE,
        }
        claims.update(overrides)
        return jwt.encode(claims, key, algorithm="RS256", headers={"kid": "synthetic-key"})

    return config, metadata, fetch, token, fetches


def rpc(client, method, params=None, bearer=None):
    headers = {
        "Accept": "application/json, text/event-stream",
        "MCP-Protocol-Version": "2025-06-18",
    }
    if bearer is not None:
        headers["Authorization"] = "Bearer " + bearer
    return client.post(
        "/mcp",
        headers=headers,
        json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}},
    )


def test_official_sdk_initialize_discovery_and_authenticated_status(oauth):
    config, _, fetch, token, _ = oauth
    reader = MagicMock(return_value={"target": TARGET, "status": "TERMINATED"})
    with TestClient(
        create_app(config, fetch=fetch, status_reader=reader), base_url="https://mcp.example.test"
    ) as client:
        metadata = client.get("/.well-known/oauth-protected-resource/mcp").json()
        assert metadata["resource"] == config.resource_url
        assert metadata["authorization_servers"] == [config.issuer_url]
        assert metadata["scopes_supported"] == [STATUS_SCOPE]
        init = rpc(
            client,
            "initialize",
            {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "synthetic", "version": "1"},
            },
            token(),
        )
        assert init.status_code == 200
        assert "tools" in init.json()["result"]["capabilities"]
        tools = rpc(client, "tools/list", bearer=token()).json()["result"]["tools"]
        assert [t["name"] for t in tools] == ["vm_status"]
        assert tools[0]["inputSchema"]["additionalProperties"] is False
        assert tools[0]["annotations"]["readOnlyHint"] is True
        assert tools[0]["annotations"]["destructiveHint"] is False
        assert tools[0]["_meta"]["securitySchemes"][0]["scopes"] == [STATUS_SCOPE]
        reader.assert_not_called()
        result = rpc(client, "tools/call", {"name": "vm_status", "arguments": {}}, token())
        assert result.status_code == 200
        assert result.json()["result"]["structuredContent"]["status"] == "TERMINATED"
        reader.assert_called_once_with()


@pytest.mark.parametrize(
    "case,expected",
    [
        ("missing", 401),
        ("invalid", 401),
        ("expired", 401),
        ("issuer", 401),
        ("audience", 401),
        ("client", 401),
        ("subject", 401),
        ("scope", 403),
        ("signature", 401),
        ("id_token", 401),
        ("oversized", 401),
        ("future", 401),
    ],
)
def test_auth_denies_before_any_cloud_access(oauth, case, expected, caplog):
    config, _, fetch, token, _ = oauth
    tokens = {
        "missing": None,
        "invalid": "PRIVATE-SENTINEL-invalid-token",
        "expired": token(exp=int(time.time()) - 1),
        "issuer": token(iss="https://wrong.example.test/"),
        "audience": token(aud="customer-api"),
        "client": token(client_id="other-client"),
        "subject": token(sub="other-user"),
        "scope": token(scope="other.scope"),
        "signature": jwt.encode({"sub": "PRIVATE-SENTINEL"}, "synthetic" * 5, algorithm="HS256"),
        "id_token": token(aud=config.client_id, scope="openid profile"),
        "oversized": "x" * 16_385,
        "future": token(iat=int(time.time()) + 500),
    }
    reader = MagicMock(side_effect=AssertionError("GCP must not be reached"))
    with TestClient(
        create_app(config, fetch=fetch, status_reader=reader), base_url="https://mcp.example.test"
    ) as client:
        result = rpc(client, "tools/call", {"name": "vm_status"}, tokens[case])
        assert result.status_code == expected
        assert "resource_metadata=" in result.headers["www-authenticate"]
        assert "PRIVATE-SENTINEL" not in result.text + caplog.text
        if tokens[case]:
            assert tokens[case] not in result.text + caplog.text
    reader.assert_not_called()


@pytest.mark.parametrize(
    "name,args",
    [
        ("vm_start", {}),
        ("vm_stop", {}),
        ("vm_exec", {"command": "PRIVATE-SENTINEL"}),
        ("unknown", {}),
        ("vm_status", {"vm": "PRIVATE-SENTINEL"}),
        ("vm_status", {"authorization": {"approved": True}}),
    ],
)
def test_only_argument_free_status_is_executable(oauth, name, args, caplog):
    config, _, fetch, token, _ = oauth
    reader = MagicMock()
    with TestClient(
        create_app(config, fetch=fetch, status_reader=reader), base_url="https://mcp.example.test"
    ) as client:
        result = rpc(client, "tools/call", {"name": name, "arguments": args}, token())
        assert result.status_code == 200
        assert result.json()["result"]["isError"] is True
        assert "PRIVATE-SENTINEL" not in result.text + caplog.text
    reader.assert_not_called()


@pytest.mark.parametrize(
    "change",
    [
        {"issuer": "https://wrong.test/"},
        {"authorization_endpoint": None},
        {"token_endpoint": "http://insecure.test/token"},
        {"jwks_uri": None},
        {"response_types_supported": ["token"]},
        {"grant_types_supported": ["client_credentials"]},
        {"code_challenge_methods_supported": ["plain"]},
        {"authorization_response_iss_parameter_supported": False},
    ],
)
def test_incompatible_real_provider_metadata_fails_startup(oauth, change):
    config, metadata, _, _, _ = oauth
    metadata.update(change)
    with pytest.raises(ConfigurationError):
        validate_authorization_server(config, lambda _: metadata)


@pytest.mark.parametrize(
    "change",
    [
        {"resource_url": "http://mcp.example.test/mcp"},
        {"resource_url": "https://mcp.example.test/wrong"},
        {"issuer_url": "https://secret@issuer.example.test/"},
        {"discovery_url": "https://different.example.test/discovery"},
        {"allowed_subjects": ()},
        {"allowed_subjects": "synthetic-owner"},
        {"allowed_subjects": (None,)},
        {"issuer_url": "https://issuer.example.test"},
        {"client_id": ""},
        {"client_claim": "anything"},
        {"callback_url": "https://attacker.test/connector"},
    ],
)
def test_invalid_operator_config_fails_closed(oauth, change):
    with pytest.raises(ConfigurationError):
        replace(oauth[0], **change)


def test_unknown_kids_are_cached_and_no_token_controlled_fetch(oauth):
    config, _, fetch, _, fetches = oauth
    verifier = OAuthTokenVerifier(config, fetch=fetch)
    for _ in range(3):
        assert verifier._verify(jwt.encode({}, "x" * 32, algorithm="HS256")) is None
    assert len(fetches) == 1  # discovery only: no invalid-alg JWKS access
    assert verifier._key("unknown") is None
    assert verifier._key("different-unknown") is None
    assert len(fetches) == 2


def test_jwks_unavailable_and_tool_failures_are_redacted(oauth, caplog):
    config, metadata, fetch, token, _ = oauth

    def broken(url):
        if url == config.discovery_url:
            return metadata
        raise ConfigurationError("metadata_unavailable")

    reader = MagicMock(side_effect=StatusUnavailable("vm_status_unavailable"))
    with TestClient(
        create_app(config, fetch=broken, status_reader=reader), base_url="https://mcp.example.test"
    ) as client:
        assert rpc(client, "tools/list", bearer=token()).status_code == 401
        reader.assert_not_called()
    with TestClient(
        create_app(config, fetch=fetch, status_reader=reader), base_url="https://mcp.example.test"
    ) as client:
        result = rpc(client, "tools/call", {"name": "vm_status"}, token())
        assert result.json()["result"]["isError"] is True
        assert result.json()["result"]["content"][0]["text"] == "vm_status_unavailable"
    assert token() not in caplog.text


def test_compute_adapter_reads_only_pinned_vm_and_filters_payload(monkeypatch):
    session = MagicMock()
    response = session.__enter__.return_value.get.return_value
    response.status_code = 200
    response.json.return_value = {
        "name": TARGET["vm"],
        "status": "TERMINATED",
        "scheduling": {"maxRunDuration": {"seconds": "1200"}, "instanceTerminationAction": "STOP"},
        "metadata": {"private": "PRIVATE-SENTINEL"},
    }
    default = MagicMock(return_value=(object(), TARGET["project"]))
    monkeypatch.setattr("google.auth.default", default)
    monkeypatch.setattr("google.auth.transport.requests.AuthorizedSession", lambda _: session)
    result = ComputeStatus()()
    assert result["status"] == "TERMINATED"
    assert result["maximum_runtime_seconds"] == 1200
    assert result["automatic_stop_configured"] is True
    assert "PRIVATE-SENTINEL" not in json.dumps(result)
    default.assert_called_once_with(scopes=["https://www.googleapis.com/auth/compute.readonly"])
    args, kwargs = session.__enter__.return_value.get.call_args
    assert args == (
        f"https://compute.googleapis.com/compute/v1/projects/{TARGET['project']}/zones/{TARGET['zone']}/instances/{TARGET['vm']}",
    )
    assert kwargs["allow_redirects"] is False
    assert kwargs["timeout"] == 10
    response.status_code = 403
    with pytest.raises(StatusUnavailable, match="^vm_status_unavailable$"):
        ComputeStatus()()


@pytest.mark.parametrize("raw", [b"[1]", b"not json", b"x" * 262_145])
def test_public_metadata_io_is_bounded_tls_verified_and_redacted(monkeypatch, raw):
    opener = MagicMock()
    opener.open.return_value.__enter__.return_value.read.return_value = raw
    factory = MagicMock(return_value=opener)
    monkeypatch.setattr("jewelai_research.https_auth.build_opener", factory)
    with pytest.raises(ConfigurationError, match="^metadata_unavailable$"):
        public_json("https://issuer.example.test/discovery")
    handlers = factory.call_args.args
    assert isinstance(handlers[0], _NoRedirect)
    assert handlers[1]._context.verify_mode == ssl.CERT_REQUIRED
    assert handlers[1]._context.check_hostname is True
    assert opener.open.call_args.kwargs == {"timeout": 5}
    assert opener.open.call_args.args[0].get_header("Authorization") is None
    opener.open.return_value.__enter__.return_value.read.assert_called_once_with(262_145)
    assert handlers[0].redirect_request(None, None, 302, None, None, "https://other.test") is None


def test_azp_client_convention_is_explicit_not_an_automatic_fallback(oauth):
    config, _, fetch, token, _ = oauth
    encoded = token(client_id=None, azp=config.client_id)
    assert OAuthTokenVerifier(config, fetch=fetch)._verify(encoded) is None
    verifier = OAuthTokenVerifier(replace(config, client_claim="azp"), fetch=fetch)
    assert verifier._verify(encoded).client_id == config.client_id


def test_transport_rejects_rebinding_before_cloud_access(oauth):
    config, _, fetch, token, _ = oauth
    reader = MagicMock()
    app = create_app(config, fetch=fetch, status_reader=reader)
    with TestClient(app, base_url="https://mcp.example.test") as client:
        result = client.post(
            "/mcp",
            headers={
                "Host": "attacker.test",
                "Authorization": "Bearer " + token(),
                "Accept": "application/json, text/event-stream",
            },
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
        )
        assert result.status_code == 421
    reader.assert_not_called()


def test_google_credential_error_payload_is_not_returned(monkeypatch):
    from google.auth.exceptions import DefaultCredentialsError

    monkeypatch.setattr(
        "google.auth.default",
        MagicMock(side_effect=DefaultCredentialsError("PRIVATE-SENTINEL")),
    )
    with pytest.raises(StatusUnavailable) as caught:
        ComputeStatus()()
    assert str(caught.value) == "vm_status_unavailable"
