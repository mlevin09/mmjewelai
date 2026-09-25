"""Bounded OIDC/JWKS verification without token-controlled network access."""

import json
import time
from collections.abc import Callable
from typing import Annotated, Any
from urllib.parse import urlparse

import httpx
import jwt
from jewelai_auth import AuthenticationError, AuthenticationUnavailableError, VerifiedIdentity
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

ASYMMETRIC_ALGORITHMS = frozenset({"RS256", "ES256"})


class OidcJwtConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    issuer: Annotated[str, Field(min_length=1, max_length=500)]
    audience: Annotated[str, Field(min_length=1, max_length=500)]
    jwks_url: Annotated[str, Field(min_length=1, max_length=2000)]
    allowed_algorithms: tuple[str, ...] = ("RS256",)
    http_timeout_seconds: Annotated[float, Field(gt=0, le=30)] = 5.0
    jwks_cache_ttl_seconds: Annotated[int, Field(gt=0, le=3600)] = 300
    leeway_seconds: Annotated[int, Field(ge=0, le=120)] = 30
    max_token_bytes: Annotated[int, Field(ge=1024, le=65536)] = 16384
    max_jwks_bytes: Annotated[int, Field(ge=1024, le=1048576)] = 262144

    @field_validator("audience")
    @classmethod
    def non_whitespace(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("value must not be whitespace")
        return value

    @field_validator("issuer")
    @classmethod
    def https_issuer(cls, value: str) -> str:
        if value != value.strip():
            raise ValueError("Issuer must not have leading or trailing whitespace")
        parsed = urlparse(value)
        if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
            raise ValueError("Issuer must be an absolute HTTPS URL without user information")
        return value

    @field_validator("jwks_url")
    @classmethod
    def https_jwks_url(cls, value: str) -> str:
        parsed = urlparse(value)
        if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
            raise ValueError("JWKS URL must be an absolute HTTPS URL without user information")
        return value

    @field_validator("allowed_algorithms")
    @classmethod
    def algorithms_are_bounded(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if not value or len(set(value)) != len(value) or not set(value) <= ASYMMETRIC_ALGORITHMS:
            raise ValueError("Allowed algorithms must be a unique subset of RS256 and ES256")
        return value


class JwksResolver:
    def __init__(
        self,
        config: OidcJwtConfig,
        *,
        client: httpx.Client | None = None,
        monotonic: Callable[[], float] = time.monotonic,
    ):
        self._config = config
        self._client = client or httpx.Client(
            timeout=config.http_timeout_seconds,
            follow_redirects=False,
        )
        self._monotonic = monotonic
        self._keys: dict[str, Any] = {}
        self._expires_at = 0.0

    def resolve(self, kid: str) -> Any:
        now = self._monotonic()
        if now >= self._expires_at:
            self._refresh(now)
        key = self._keys.get(kid)
        if key is None:
            self._refresh(now)
            key = self._keys.get(kid)
        if key is None:
            raise AuthenticationError("Bearer token signing key is not recognized")
        return key

    def _refresh(self, now: float) -> None:
        try:
            with self._client.stream(
                "GET",
                self._config.jwks_url,
                timeout=self._config.http_timeout_seconds,
            ) as response:
                if response.status_code != 200:
                    raise AuthenticationUnavailableError("Identity key service is unavailable")
                chunks = bytearray()
                for chunk in response.iter_bytes():
                    chunks.extend(chunk)
                    if len(chunks) > self._config.max_jwks_bytes:
                        raise AuthenticationUnavailableError(
                            "Identity key response exceeds size limit"
                        )
                content = bytes(chunks)
            document = json.loads(content)
            raw_keys = document.get("keys") if isinstance(document, dict) else None
            if not isinstance(raw_keys, list):
                raise AuthenticationUnavailableError("Identity key response is invalid")
            parsed: dict[str, Any] = {}
            for item in raw_keys:
                if not isinstance(item, dict) or not isinstance(item.get("kid"), str):
                    continue
                algorithm = item.get("alg")
                if algorithm is not None and algorithm not in self._config.allowed_algorithms:
                    continue
                parsed[item["kid"]] = jwt.PyJWK.from_dict(item).key
            if not parsed:
                raise AuthenticationUnavailableError(
                    "Identity key response contains no usable keys"
                )
        except AuthenticationUnavailableError:
            raise
        except (
            httpx.HTTPError,
            json.JSONDecodeError,
            jwt.PyJWTError,
            ValueError,
            TypeError,
        ) as exc:
            raise AuthenticationUnavailableError("Identity key service is unavailable") from exc
        self._keys = parsed
        self._expires_at = now + self._config.jwks_cache_ttl_seconds


class OidcJwtVerifier:
    def __init__(
        self,
        config: OidcJwtConfig,
        *,
        resolver: JwksResolver | None = None,
        http_client: httpx.Client | None = None,
    ):
        self.config = config
        self._resolver = resolver or JwksResolver(config, client=http_client)

    def verify(self, token: str) -> VerifiedIdentity:
        if (
            not isinstance(token, str)
            or not token
            or len(token.encode("utf-8")) > self.config.max_token_bytes
        ):
            raise AuthenticationError("Bearer token is invalid")
        try:
            header = jwt.get_unverified_header(token)
            algorithm = header.get("alg")
            kid = header.get("kid")
            if (
                algorithm not in self.config.allowed_algorithms
                or not isinstance(kid, str)
                or not kid
            ):
                raise AuthenticationError("Bearer token is invalid")
            key = self._resolver.resolve(kid)
            claims = jwt.decode(
                token,
                key,
                algorithms=list(self.config.allowed_algorithms),
                audience=self.config.audience,
                issuer=self.config.issuer,
                leeway=self.config.leeway_seconds,
                options={"require": ["iss", "aud", "sub", "exp"]},
            )
            subject = claims["sub"]
            if (
                not isinstance(subject, str)
                or not subject
                or subject != subject.strip()
                or len(subject) > 255
            ):
                raise AuthenticationError("Bearer token is invalid")
            email = claims.get("email") if claims.get("email_verified") is True else None
            if not isinstance(email, str):
                email = None
            name = claims.get("name")
            if not isinstance(name, str):
                name = None
            return VerifiedIdentity(
                issuer=self.config.issuer,
                subject=subject,
                email=email,
                display_name=name,
            )
        except (AuthenticationError, AuthenticationUnavailableError):
            raise
        except (jwt.PyJWTError, ValidationError, KeyError, ValueError, TypeError) as exc:
            raise AuthenticationError("Bearer token is invalid") from exc
