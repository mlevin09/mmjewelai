from datetime import UTC, datetime, timedelta

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from jewelai_auth import AuthenticationError, AuthenticationUnavailableError
from pydantic import ValidationError

from jewelai_auth_oidc import JwksResolver, OidcJwtConfig, OidcJwtVerifier

ISSUER = "https://issuer.test"
AUDIENCE = "jewelai-api"
JWKS_URL = "https://issuer.test/keys"


@pytest.fixture(scope="module")
def keys():
    first = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    second = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return first, second


def jwk(private_key, kid="key-1"):
    value = jwt.algorithms.RSAAlgorithm.to_jwk(private_key.public_key(), as_dict=True)
    value.update({"kid": kid, "alg": "RS256", "use": "sig"})
    return value


def claims(**changes):
    now = datetime.now(UTC)
    value = {
        "iss": ISSUER,
        "aud": AUDIENCE,
        "sub": "subject-1",
        "exp": now + timedelta(minutes=5),
        "iat": now,
    }
    value.update(changes)
    return value


def token(private_key, *, kid="key-1", headers=None, algorithm="RS256", **changes):
    merged = {"kid": kid, **(headers or {})}
    return jwt.encode(claims(**changes), private_key, algorithm=algorithm, headers=merged)


def verifier(keys, handler=None, **config_changes):
    private, _ = keys
    handler = handler or (lambda request: httpx.Response(200, json={"keys": [jwk(private)]}))
    client = httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=False)
    config = OidcJwtConfig(
        issuer=ISSUER,
        audience=AUDIENCE,
        jwks_url=JWKS_URL,
        **config_changes,
    )
    return OidcJwtVerifier(config, http_client=client)


def test_valid_rs256_token_and_verified_email_metadata(keys):
    private, _ = keys
    identity = verifier(keys).verify(
        token(
            private,
            email="person@example.test",
            email_verified=True,
            name="Person",
            role="owner",
            organization_id="ignored",
            groups=["admins"],
        )
    )
    assert identity.subject == "subject-1"
    assert identity.email == "person@example.test"
    assert identity.display_name == "Person"
    assert not hasattr(identity, "role")


def test_unverified_or_string_verified_email_is_ignored(keys):
    private, _ = keys
    for verified in (False, "true", None):
        identity = verifier(keys).verify(
            token(private, email="person@example.test", email_verified=verified)
        )
        assert identity.email is None


@pytest.mark.parametrize(
    ("changes", "expected"),
    [
        ({"iss": "https://wrong.test"}, AuthenticationError),
        ({"aud": "wrong"}, AuthenticationError),
        ({"exp": datetime.now(UTC) - timedelta(minutes=5)}, AuthenticationError),
        ({"nbf": datetime.now(UTC) + timedelta(minutes=5)}, AuthenticationError),
        ({"sub": " "}, AuthenticationError),
        ({"sub": None}, AuthenticationError),
        ({"exp": None}, AuthenticationError),
    ],
)
def test_invalid_claims_are_rejected_without_details(keys, changes, expected):
    private, _ = keys
    with pytest.raises(expected, match="Bearer token is invalid"):
        verifier(keys).verify(token(private, **changes))


def test_missing_required_claims_are_rejected(keys):
    private, _ = keys
    value = claims()
    del value["sub"]
    encoded = jwt.encode(value, private, algorithm="RS256", headers={"kid": "key-1"})
    with pytest.raises(AuthenticationError):
        verifier(keys).verify(encoded)


def test_invalid_signature_malformed_and_oversized_tokens_are_rejected(keys):
    private, other = keys
    instance = verifier(keys)
    for value in (token(other), "not-a-jwt", "x" * 16385):
        with pytest.raises(AuthenticationError) as caught:
            instance.verify(value)
        assert value not in str(caught.value)


def test_symmetric_and_none_algorithms_are_rejected(keys):
    symmetric = jwt.encode(claims(), "s" * 32, algorithm="HS256", headers={"kid": "key-1"})
    unsigned = jwt.encode(claims(), None, algorithm="none", headers={"kid": "key-1"})
    instance = verifier(keys)
    for value in (symmetric, unsigned):
        with pytest.raises(AuthenticationError):
            instance.verify(value)


def test_unknown_kid_causes_exactly_one_forced_refresh(keys):
    private, _ = keys
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json={"keys": [jwk(private)]})

    with pytest.raises(AuthenticationError, match="signing key"):
        verifier(keys, handler).verify(token(private, kid="unknown"))
    assert len(requests) == 2


def test_cache_reuses_key_and_refreshes_after_ttl(keys):
    private, _ = keys
    calls = 0
    now = [10.0]

    def handler(_):
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={"keys": [jwk(private)]})

    config = OidcJwtConfig(issuer=ISSUER, audience=AUDIENCE, jwks_url=JWKS_URL)
    resolver = JwksResolver(
        config,
        client=httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=False),
        monotonic=lambda: now[0],
    )
    instance = OidcJwtVerifier(config, resolver=resolver)
    instance.verify(token(private))
    instance.verify(token(private))
    assert calls == 1
    now[0] += 301
    instance.verify(token(private))
    assert calls == 2


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(503),
        httpx.Response(200, content=b"not-json"),
        httpx.Response(200, json={}),
        httpx.Response(200, json={"keys": []}),
    ],
)
def test_jwks_failures_are_safe_unavailable(keys, response):
    private, _ = keys
    with pytest.raises(AuthenticationUnavailableError, match="Identity key"):
        verifier(keys, lambda _: response).verify(token(private))


def test_jwks_size_is_bounded(keys):
    private, _ = keys
    with pytest.raises(AuthenticationUnavailableError, match="size limit"):
        verifier(
            keys, lambda _: httpx.Response(200, content=b"x" * 1025), max_jwks_bytes=1024
        ).verify(token(private))


def test_token_controlled_urls_are_ignored(keys):
    private, _ = keys
    requested = []

    def handler(request):
        requested.append(str(request.url))
        return httpx.Response(200, json={"keys": [jwk(private)]})

    value = token(
        private,
        headers={"jku": "https://attacker.test/jwks", "x5u": "https://attacker.test/cert"},
    )
    verifier(keys, handler).verify(value)
    assert requested == [JWKS_URL]


def test_jwks_redirect_is_not_followed_and_timeout_is_bounded(keys):
    private, _ = keys
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(302, headers={"location": "https://attacker.test/keys"})

    with pytest.raises(AuthenticationUnavailableError):
        verifier(keys, handler, http_timeout_seconds=3).verify(token(private))
    assert [str(request.url) for request in requests] == [JWKS_URL]
    assert requests[0].extensions["timeout"]["connect"] == 3


@pytest.mark.parametrize(
    "changes",
    [
        {"issuer": "http://issuer.test"},
        {"jwks_url": "http://issuer.test/keys"},
        {"allowed_algorithms": ("HS256",)},
        {"http_timeout_seconds": 0},
        {"jwks_cache_ttl_seconds": 3601},
        {"leeway_seconds": 121},
    ],
)
def test_invalid_configuration_fails_closed(changes):
    values = {"issuer": ISSUER, "audience": AUDIENCE, "jwks_url": JWKS_URL, **changes}
    with pytest.raises(ValidationError):
        OidcJwtConfig(**values)
