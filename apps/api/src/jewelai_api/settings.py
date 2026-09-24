"""Environment-backed runtime configuration with explicit artifact pins."""

import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class ArtifactVersions:
    roles: str = "1.0.0"
    dictionary: str = "1.0.0"
    questions: str = "1.0.0"
    rules: str = "1.0.0"


@dataclass(frozen=True)
class RuntimeSettings:
    database_url: str = "sqlite+pysqlite:///./jewelai-v2.db"
    repository_root: Path = field(default_factory=lambda: Path(__file__).resolve().parents[4])
    artifacts: ArtifactVersions = field(default_factory=ArtifactVersions)

    @classmethod
    def from_environment(cls) -> "RuntimeSettings":
        root = os.getenv("JEWELAI_REPOSITORY_ROOT")
        return cls(
            database_url=os.getenv("DATABASE_URL", cls.database_url),
            repository_root=Path(root).resolve() if root else Path(__file__).resolve().parents[4],
            artifacts=ArtifactVersions(
                roles=os.getenv("ROLE_ARTIFACT_VERSION", "1.0.0"),
                dictionary=os.getenv("DICTIONARY_ARTIFACT_VERSION", "1.0.0"),
                questions=os.getenv("QUESTION_ARTIFACT_VERSION", "1.0.0"),
                rules=os.getenv("RULES_ARTIFACT_VERSION", "1.0.0"),
            ),
        )
