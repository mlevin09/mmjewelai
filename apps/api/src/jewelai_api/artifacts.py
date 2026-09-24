"""Deterministic loading of one explicitly versioned runtime artifact bundle."""

from dataclasses import dataclass
from pathlib import Path

from jewelai_domain import (
    DictionaryRegistry,
    QuestionCatalog,
    RoleRegistry,
    RuleRegistry,
    load_domain_dictionary,
    load_question_catalog,
    load_role_profiles,
    load_rules,
)

from .settings import ArtifactVersions


class ArtifactConfigurationError(RuntimeError):
    pass


@dataclass(frozen=True)
class RuntimeArtifacts:
    roles: RoleRegistry
    dictionary: DictionaryRegistry
    questions: QuestionCatalog
    rules: RuleRegistry
    versions: ArtifactVersions


def load_runtime_artifacts(root: Path, versions: ArtifactVersions) -> RuntimeArtifacts:
    paths = {
        "roles": root / "data" / "roles" / f"v{versions.roles}.json",
        "dictionary": root / "data" / "dictionary" / f"v{versions.dictionary}.json",
        "questions": root / "data" / "questions" / f"v{versions.questions}.json",
        "rules": root / "data" / "rules" / f"v{versions.rules}.json",
    }
    missing = tuple(str(path) for path in paths.values() if not path.is_file())
    if missing:
        raise ArtifactConfigurationError(f"Configured artifact files are missing: {missing}")
    try:
        roles = load_role_profiles(paths["roles"])
        dictionary = load_domain_dictionary(paths["dictionary"])
        questions = load_question_catalog(paths["questions"], roles=roles, dictionary=dictionary)
        rules = load_rules(paths["rules"], roles=roles, dictionary=dictionary, questions=questions)
    except (ValueError, KeyError) as exc:
        raise ArtifactConfigurationError("Configured artifacts failed cross-validation") from exc
    actual = ArtifactVersions(
        roles=roles.artifact_version,
        dictionary=dictionary.artifact_version,
        questions=questions.artifact_version,
        rules=rules.artifact_version,
    )
    if actual != versions:
        raise ArtifactConfigurationError(
            f"Configured artifact versions {versions} do not match loaded versions {actual}"
        )
    return RuntimeArtifacts(roles, dictionary, questions, rules, versions)
