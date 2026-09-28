from collections.abc import Mapping
from typing import Any

import pytest
from google.auth import exceptions as google_auth_exceptions
from jewelai_auth import AuthenticationError, AuthenticationUnavailableError

from jewelai_auth_identity_platform import IdentityPlatformConfig, IdentityPlatformTokenVerifier

PROJECT = "mmjewellai-preprod"
NOW = 2_000_000_000


def claims(**changes: Any) -> dict[str, Any]:
    value = {
        "iss": f"https://securetoken.google.com/{PROJECT}",
        "aud": PROJECT,
        "sub": "firebase-uid-1",
        "iat": NOW - 10,
        "exp": NOW + 3600,
        "auth_time": NOW - 20,
        "email": "user@example.test",
        "email_verified": True,
        "name": "Test User",
    }
    value.update(changes)
    return value


def verifier(result: Mapping[str, Any] | None) -> IdentityPlatformTokenVerifier:
    def decode(token, request, audience):
        assert token == "signed-token"
        assert request is not None
        assert audience == PROJECT
        return result

    return IdentityPlatformTokenVerifier(
        IdentityPlatformConfig(project_id=PROJECT), decoder=decode, clock=lambda: NOW
    )


def test_valid_token_maps_exact_external_identity() -> None:
    identity = verifier(claims()).verify("signed-token")
    assert identity.issuer == f"https://securetoken.google.com/{PROJECT}"
    assert identity.subject == "firebase-uid-1"
    assert identity.email == "user@example.test"


@pytest.mark.parametrize(
    "changes",
    [
        {"iss": "https://securetoken.google.com/wrong-project"},
        {"aud": "wrong-project"},
        {"exp": NOW - 100},
        {"iat": NOW + 100},
        {"auth_time": NOW + 100},
        {"sub": ""},
        {"sub": " surrounded "},
    ],
)
def test_invalid_claims_are_rejected(changes) -> None:
    with pytest.raises(AuthenticationError, match="Bearer token is invalid"):
        verifier(claims(**changes)).verify("signed-token")


def test_invalid_signature_from_google_verifier_is_rejected() -> None:
    def decode(*_):
        raise google_auth_exceptions.MalformedError("bad signature")

    instance = IdentityPlatformTokenVerifier(
        IdentityPlatformConfig(project_id=PROJECT), decoder=decode
    )
    with pytest.raises(AuthenticationError, match="Bearer token is invalid"):
        instance.verify("signed-token")


def test_key_service_failure_is_typed() -> None:
    def decode(*_):
        raise google_auth_exceptions.TransportError("offline")

    instance = IdentityPlatformTokenVerifier(
        IdentityPlatformConfig(project_id=PROJECT), decoder=decode
    )
    with pytest.raises(AuthenticationUnavailableError, match="Identity key service"):
        instance.verify("signed-token")


@pytest.mark.parametrize("token", ["", None])
def test_malformed_bearer_token_is_rejected(token) -> None:
    with pytest.raises(AuthenticationError, match="Bearer token is invalid"):
        verifier(claims()).verify(token)
