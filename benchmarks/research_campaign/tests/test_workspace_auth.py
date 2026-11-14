"""Only the new connection's OAuth exchange and denial boundaries; no campaign."""

import base64
import hashlib
from urllib.parse import parse_qs, urlparse

import pytest
from starlette.routing import Route
from starlette.testclient import TestClient
from test_https_gateway import rpc

from jewelai_research.https_auth import OAuthConfig
from jewelai_research.https_gateway import create_app
from jewelai_research.native_jobs import EXECUTE_SCOPE, READ_SCOPE
from jewelai_research.workspace_auth import CALLBACK, CLIENT, WorkspaceAuth


@pytest.fixture
def connected(tmp_path):
    origin = "https://research.example.test"
    provider = WorkspaceAuth(
        tmp_path / "auth",
        origin,
        "existing-project",
        "existing-owner",
        "public-browser-key",
        verify=lambda token: "existing-owner" if token == "valid-id" else "other",
    )

    class Actions:
        def call(self, principal, name, args):
            assert principal.subject == "existing-owner"
            return {"status": "bound-to-existing-runner"}

    cfg = OAuthConfig(
        origin + "/mcp",
        origin + "/",
        origin + "/.well-known/oauth-authorization-server",
        CLIENT,
        ["existing-owner"],
        CALLBACK,
    )
    app = create_app(cfg, native_actions=Actions(), auth_provider=provider)
    app.routes[:] = [
        r
        for r in app.routes
        if r.path not in {"/.well-known/oauth-authorization-server", "/revoke"}
    ]
    app.routes.extend(
        [
            Route("/.well-known/oauth-authorization-server", provider.metadata),
            Route("/consent", provider.consent),
            Route("/consent", provider.confirm, methods=["POST"]),
            Route("/revoke", provider.revocation, methods=["POST"]),
        ]
    )
    with TestClient(app, base_url=origin) as client:
        yield client, provider


def authorize(client):
    verifier = "a" * 64
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    )
    response = client.get(
        "/authorize",
        params={
            "client_id": CLIENT,
            "redirect_uri": CALLBACK,
            "response_type": "code",
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "scope": READ_SCOPE + " " + EXECUTE_SCOPE,
            "resource": "https://research.example.test/mcp",
            "state": "client-state",
        },
        follow_redirects=False,
    )
    assert response.status_code == 302, response.text
    ticket = urlparse(response.headers["location"]).fragment
    response = client.get(response.headers["location"])
    assert response.status_code == 200
    csrf = client.cookies.get("research-consent")
    return verifier, ticket, csrf


def exchange(client, verifier, ticket, csrf, token="valid-id"):
    response = client.post(
        "/consent",
        headers={"Origin": "https://research.example.test"},
        json={"ticket": ticket, "csrf": csrf, "id_token": token},
    )
    if response.status_code != 200:
        return response
    parsed = parse_qs(urlparse(response.json()["redirect"]).query)
    assert parsed["state"] == ["client-state"] and parsed["iss"] == [
        "https://research.example.test/"
    ]
    return client.post(
        "/token",
        data={
            "grant_type": "authorization_code",
            "client_id": CLIENT,
            "redirect_uri": CALLBACK,
            "code": parsed["code"][0],
            "code_verifier": verifier,
            "resource": "https://research.example.test/mcp",
        },
    )


def test_real_sdk_pkce_login_refresh_revoke_and_hashed_storage(connected):
    client, provider = connected
    assert rpc(client, "tools/list").status_code == 401
    v, ticket, csrf = authorize(client)
    result = exchange(client, v, ticket, csrf)
    assert result.status_code == 200, result.text
    tokens = result.json()
    assert rpc(client, "tools/list", bearer=tokens["access_token"]).status_code == 200
    refresh = client.post(
        "/token",
        data={
            "grant_type": "refresh_token",
            "client_id": CLIENT,
            "refresh_token": tokens["refresh_token"],
        },
    )
    assert refresh.status_code == 200, refresh.text
    assert rpc(client, "tools/list", bearer=tokens["access_token"]).status_code == 401
    rotated = refresh.json()
    assert (
        rpc(
            client,
            "tools/call",
            {"name": "native_runner_catalog", "arguments": {}},
            bearer=rotated["access_token"],
        ).json()["result"]["structuredContent"]["status"]
        == "bound-to-existing-runner"
    )
    assert all(
        raw.encode() not in provider.path.read_bytes()
        for raw in [
            tokens["access_token"],
            tokens["refresh_token"],
            rotated["access_token"],
            rotated["refresh_token"],
        ]
    )
    assert (
        client.post(
            "/revoke", data={"client_id": CLIENT, "token": rotated["refresh_token"]}
        ).status_code
        == 200
    )
    assert rpc(client, "tools/list", bearer=rotated["access_token"]).status_code == 401


@pytest.mark.parametrize("failure", ["wrong_identity", "csrf", "pkce"])
def test_identity_csrf_and_pkce_fail_closed(connected, failure):
    client, _ = connected
    v, ticket, csrf = authorize(client)
    r = exchange(
        client,
        "b" * 64 if failure == "pkce" else v,
        ticket,
        "wrong" if failure == "csrf" else csrf,
        "wrong-id" if failure == "wrong_identity" else "valid-id",
    )
    assert r.status_code in (400, 403)
    assert rpc(client, "tools/list").status_code == 401


def test_discovery_exposes_only_static_pkce_client_and_rejects_arbitrary_redirect(connected):
    client, _ = connected
    m = client.get("/.well-known/oauth-authorization-server").json()
    assert m["authorization_response_iss_parameter_supported"] and m[
        "token_endpoint_auth_methods_supported"
    ] == ["none"]
    assert "registration_endpoint" not in m
    r = client.get(
        "/authorize",
        params={
            "client_id": CLIENT,
            "redirect_uri": "https://attacker.invalid",
            "response_type": "code",
        },
        follow_redirects=False,
    )
    assert r.status_code == 400 and "location" not in r.headers
