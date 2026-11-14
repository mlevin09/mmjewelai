"""JWT access-token verification for the read-only MCP resource server.

This is not an authorization server. A real, separately registered OAuth client
and PKCE-capable issuer are deployment prerequisites. No token passthrough.
"""

import json
import ssl
import threading
import time
from dataclasses import dataclass
from urllib.error import URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, HTTPSHandler, Request, build_opener

import anyio
import certifi
import jwt
from mcp.server.auth.provider import AccessToken
from pydantic import AnyHttpUrl

STATUS_SCOPE = "jewelai.research.vm.status"


class ConfigurationError(ValueError):
    """Contains only a bounded reason, never remote payloads or credentials."""


def https_url(value: str) -> str:
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.fragment
        or parsed.query
        or parsed.port not in (None, 443)
    ):
        raise ConfigurationError("https_url_required")
    return value


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def public_json(url: str) -> dict:
    """Fetch only operator-pinned public metadata, with bounded I/O, no redirects."""
    https_url(url)
    try:
        request = Request(url, headers={"Accept": "application/json"})
        # Same maintained CA bundle as Requests/Google Auth; never disable TLS
        # verification when the host Python lacks a configured system trust store.
        tls = HTTPSHandler(context=ssl.create_default_context(cafile=certifi.where()))
        with build_opener(_NoRedirect(), tls).open(request, timeout=5) as response:
            raw = response.read(262_145)
        if len(raw) > 262_144:
            raise ConfigurationError("metadata_too_large")
        result = json.loads(raw)
        if not isinstance(result, dict):
            raise ConfigurationError("metadata_invalid")
        return result
    except (URLError, OSError, ValueError):
        raise ConfigurationError("metadata_unavailable") from None


@dataclass(frozen=True)
class OAuthConfig:
    resource_url: str
    issuer_url: str
    discovery_url: str
    client_id: str
    allowed_subjects: tuple[str, ...]
    callback_url: str
    client_claim: str = "client_id"

    def __post_init__(self):
        for url in (self.resource_url, self.issuer_url, self.discovery_url, self.callback_url):
            https_url(url)
        for url in (self.resource_url, self.issuer_url):
            if str(AnyHttpUrl(url)) != url:
                raise ConfigurationError("canonical_resource_and_issuer_urls_required")
        if urlsplit(self.resource_url).path != "/mcp":
            raise ConfigurationError("resource_path_must_be_mcp")
        if urlsplit(self.discovery_url).netloc != urlsplit(self.issuer_url).netloc:
            raise ConfigurationError("discovery_must_belong_to_issuer")
        if urlsplit(self.callback_url).netloc != "chatgpt.com" or not urlsplit(
            self.callback_url
        ).path.startswith("/connector"):
            raise ConfigurationError("chatgpt_callback_required")
        if (
            not isinstance(self.client_id, str)
            or not self.client_id
            or not isinstance(self.allowed_subjects, (tuple, list))
            or not self.allowed_subjects
            or any(not isinstance(subject, str) or not subject for subject in self.allowed_subjects)
        ):
            raise ConfigurationError("registered_client_and_subjects_required")
        if self.client_claim not in ("client_id", "azp"):
            raise ConfigurationError("unsupported_client_claim")


def validate_authorization_server(config: OAuthConfig, fetch=public_json) -> str:
    """Require real discovery; registration is pre-registered, never fabricated.

    The issuer administrator must register the exact ChatGPT callback and MCP
    resource/audience + scope. Discovery cannot prove that administrative step.
    """
    metadata = fetch(config.discovery_url)
    if metadata.get("issuer") != config.issuer_url:
        raise ConfigurationError("issuer_mismatch")
    for name in ("authorization_endpoint", "token_endpoint", "jwks_uri"):
        value = metadata.get(name)
        if not isinstance(value, str):
            raise ConfigurationError("oauth_endpoint_missing")
        https_url(value)
    if (
        "code" not in metadata.get("response_types_supported", [])
        or "authorization_code" not in metadata.get("grant_types_supported", [])
        or "S256" not in metadata.get("code_challenge_methods_supported", [])
    ):
        raise ConfigurationError("authorization_code_pkce_required")
    # The shared redirect is safe only with RFC 9207 issuer identification.
    if (
        config.callback_url == "https://chatgpt.com/connector_platform_oauth_redirect"
        and metadata.get("authorization_response_iss_parameter_supported") is not True
    ):
        raise ConfigurationError("callback_requires_issuer_identification")
    return metadata["jwks_uri"]


class OAuthTokenVerifier:
    def __init__(self, config: OAuthConfig, *, fetch=public_json, clock=time.monotonic):
        self.config = config
        self.fetch = fetch
        self.clock = clock
        self.jwks_url = validate_authorization_server(config, fetch)
        self._keys: dict = {}
        self._keys_until = 0.0
        self._lock = threading.Lock()

    def _key(self, kid: str):
        with self._lock:
            # Unknown kids cannot cause unbounded network calls. Rotation is
            # observed within five minutes; failed fetches are briefly cached.
            if self.clock() >= self._keys_until:
                self._keys = {}
                self._keys_until = self.clock() + 10
                document = self.fetch(self.jwks_url)
                keys = document.get("keys")
                if not isinstance(keys, list) or not 1 <= len(keys) <= 32:
                    raise ConfigurationError("jwks_invalid")
                admitted = {}
                for key in keys:
                    if (
                        isinstance(key, dict)
                        and key.get("kty") == "RSA"
                        and key.get("use", "sig") == "sig"
                        and key.get("alg", "RS256") == "RS256"
                        and key.get("key_ops", ["verify"]) == ["verify"]
                        and isinstance(key.get("kid"), str)
                    ):
                        if key["kid"] in admitted:
                            raise ConfigurationError("jwks_duplicate_kid")
                        public_key = jwt.PyJWK.from_dict(key, algorithm="RS256").key
                        if public_key.key_size < 2048:
                            raise ConfigurationError("jwks_weak_key")
                        admitted[key["kid"]] = public_key
                self._keys = admitted
                self._keys_until = self.clock() + 300
            return self._keys.get(kid)

    def _verify(self, token: str) -> AccessToken | None:
        try:
            if not isinstance(token, str) or not 1 <= len(token) <= 16_384:
                return None
            header = jwt.get_unverified_header(token)
            if header.get("alg") != "RS256" or not isinstance(header.get("kid"), str):
                return None
            key = self._key(header["kid"])
            if key is None:
                return None
            claims = jwt.decode(
                token,
                key,
                algorithms=["RS256"],
                issuer=self.config.issuer_url,
                audience=self.config.resource_url,
                options={"require": ["iss", "aud", "exp", "iat", "sub"], "strict_aud": True},
            )
            subject = claims["sub"]
            if (
                subject not in self.config.allowed_subjects
                or claims.get(self.config.client_claim) != self.config.client_id
                or not isinstance(claims.get("scope"), str)
                or not isinstance(claims["exp"], int)
                or isinstance(claims["exp"], bool)
            ):
                return None
            # SDK enforces required scope with a safe 403 before tool execution.
            return AccessToken(
                token=token,
                client_id=self.config.client_id,
                scopes=claims["scope"].split(),
                expires_at=claims["exp"],
                resource=self.config.resource_url,
                subject=subject,
                claims={"iss": self.config.issuer_url},
            )
        except (jwt.PyJWTError, ConfigurationError, TypeError, ValueError):
            return None

    async def verify_token(self, token: str) -> AccessToken | None:
        return await anyio.to_thread.run_sync(self._verify, token)
