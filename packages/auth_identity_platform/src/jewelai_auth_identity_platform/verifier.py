"""Google-supported verification for Identity Platform / Firebase ID tokens."""

import time
from collections.abc import Callable, Mapping
from typing import Annotated, Any

from google.auth import exceptions as google_auth_exceptions
from google.auth.transport.requests import Request
from google.oauth2.id_token import verify_firebase_token
from jewelai_auth import AuthenticationError, AuthenticationUnavailableError, VerifiedIdentity
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator


class IdentityPlatformConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    project_id: Annotated[str, Field(min_length=6, max_length=30, pattern=r"^[a-z][a-z0-9-]+$")]
    max_token_bytes: Annotated[int, Field(ge=1024, le=65536)] = 16384
    clock_skew_seconds: Annotated[int, Field(ge=0, le=120)] = 30

    @field_validator("project_id")
    @classmethod
    def exact_project_id(cls, value: str) -> str:
        if value != value.strip():
            raise ValueError("Identity Platform project ID must be exact")
        return value

    @property
    def issuer(self) -> str:
        return f"https://securetoken.google.com/{self.project_id}"


TokenDecoder = Callable[[str, Request, str], Mapping[str, Any] | None]


def _decode(token: str, request: Request, audience: str) -> Mapping[str, Any] | None:
    return verify_firebase_token(token, request, audience=audience)


class IdentityPlatformTokenVerifier:
    def __init__(
        self,
        config: IdentityPlatformConfig,
        *,
        decoder: TokenDecoder = _decode,
        request: Request | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.config = config
        self._decoder = decoder
        self._request = request or Request()
        self._clock = clock

    def verify(self, token: str) -> VerifiedIdentity:
        if (
            not isinstance(token, str)
            or not token
            or len(token.encode("utf-8")) > self.config.max_token_bytes
        ):
            raise AuthenticationError("Bearer token is invalid")
        try:
            claims = self._decoder(token, self._request, self.config.project_id)
        except google_auth_exceptions.TransportError as exc:
            raise AuthenticationUnavailableError("Identity key service is unavailable") from exc
        except (google_auth_exceptions.GoogleAuthError, ValueError, TypeError) as exc:
            raise AuthenticationError("Bearer token is invalid") from exc
        if not isinstance(claims, Mapping):
            raise AuthenticationError("Bearer token is invalid")
        try:
            now = self._clock()
            issuer = claims.get("iss")
            audience = claims.get("aud")
            subject = claims.get("sub")
            issued_at = claims.get("iat")
            expires_at = claims.get("exp")
            auth_time = claims.get("auth_time")
            if issuer != self.config.issuer or audience != self.config.project_id:
                raise AuthenticationError("Bearer token is invalid")
            if (
                not isinstance(subject, str)
                or not subject
                or subject != subject.strip()
                or len(subject) > 255
            ):
                raise AuthenticationError("Bearer token is invalid")
            if any(
                isinstance(value, bool) or not isinstance(value, (int, float))
                for value in (
                    issued_at,
                    expires_at,
                    auth_time,
                )
            ):
                raise AuthenticationError("Bearer token is invalid")
            if issued_at > now + self.config.clock_skew_seconds:
                raise AuthenticationError("Bearer token is invalid")
            if auth_time > now + self.config.clock_skew_seconds:
                raise AuthenticationError("Bearer token is invalid")
            if expires_at <= now - self.config.clock_skew_seconds:
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
        except AuthenticationError:
            raise
        except (ValidationError, ValueError, TypeError) as exc:
            raise AuthenticationError("Bearer token is invalid") from exc
