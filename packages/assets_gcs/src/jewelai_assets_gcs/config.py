"""Explicit non-secret configuration for the GCS Asset adapter."""

import re
from dataclasses import dataclass

_BUCKET_NAME = re.compile(r"^[a-z0-9][a-z0-9._-]{1,220}[a-z0-9]$")
_PROJECT_ID = re.compile(r"^[a-z][a-z0-9-]{4,61}[a-z0-9]$")
_SERVICE_ACCOUNT_EMAIL = re.compile(
    r"^[a-z0-9][a-z0-9-]{4,62}[a-z0-9]@"
    r"[a-z][a-z0-9-]{4,61}[a-z0-9]\.iam\.gserviceaccount\.com$"
)


def validate_signing_service_account_email(value: str) -> str:
    """Validate a bounded Google service-account signing identity."""
    if len(value) > 254 or not _SERVICE_ACCOUNT_EMAIL.fullmatch(value):
        raise ValueError("GCS signing service-account email is invalid")
    return value


@dataclass(frozen=True)
class GcsAssetStorageConfig:
    bucket_name: str
    project_id: str | None = None
    signing_service_account_email: str | None = None

    def __post_init__(self) -> None:
        if not _BUCKET_NAME.fullmatch(self.bucket_name):
            raise ValueError("GCS asset bucket name is invalid")
        if self.project_id is not None and not _PROJECT_ID.fullmatch(self.project_id):
            raise ValueError("GCP project ID is invalid")
        if self.signing_service_account_email is not None:
            validate_signing_service_account_email(self.signing_service_account_email)
