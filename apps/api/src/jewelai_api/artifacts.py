"""Deterministic loading of one explicitly versioned runtime artifact bundle."""

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

from jewelai_domain import (
    DictionaryRegistry,
    ParametricKnowledgeBundle,
    QuestionCatalog,
    RoleRegistry,
    RuleRegistry,
    load_domain_dictionary,
    load_parametric_knowledge,
    load_question_catalog,
    load_role_profiles,
    load_rules,
)
from jewelai_prompts import PromptTemplateBundle, load_prompt_templates

from .settings import ArtifactVersions


class ArtifactConfigurationError(RuntimeError):
    pass


@dataclass(frozen=True)
class RuntimeArtifacts:
    roles: RoleRegistry
    dictionary: DictionaryRegistry
    questions: QuestionCatalog
    rules: RuleRegistry
    prompts: PromptTemplateBundle
    parametric_knowledge: ParametricKnowledgeBundle
    versions: ArtifactVersions
    source_root: Path | None = None
    artifact_hashes: tuple[tuple[str, str], ...] = ()


def load_runtime_artifacts(root: Path, versions: ArtifactVersions) -> RuntimeArtifacts:
    # A version is a trusted server pin, never an arbitrary path supplied by a client.
    if any(
        not isinstance(version, str) or not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", version)
        for version in vars(versions).values()
    ):
        raise ArtifactConfigurationError("Artifact pins must be exact semantic versions")
    paths = {
        "roles": root / "data" / "roles" / f"v{versions.roles}.json",
        "dictionary": root / "data" / "dictionary" / f"v{versions.dictionary}.json",
        "questions": root / "data" / "questions" / f"v{versions.questions}.json",
        "rules": root / "data" / "rules" / f"v{versions.rules}.json",
        "prompts": root / "data" / "prompts" / f"v{versions.prompts}.json",
        "knowledge_base": root / "data" / "knowledge-base" / f"v{versions.knowledge_base}.json",
    }
    missing = tuple(str(path) for path in paths.values() if not path.is_file())
    if missing:
        raise ArtifactConfigurationError(f"Configured artifact files are missing: {missing}")
    if (versions.questions, versions.rules) not in {
        ("1.0.0", "1.0.0"),
        ("2.0.0", "2.0.0"),
    }:
        raise ArtifactConfigurationError("Unsupported Question/Rules profile tuple")
    hashes = tuple(
        sorted((key, hashlib.sha256(path.read_bytes()).hexdigest()) for key, path in paths.items())
    )
    try:
        roles = load_role_profiles(paths["roles"])
        dictionary = load_domain_dictionary(paths["dictionary"])
        questions = load_question_catalog(paths["questions"], roles=roles, dictionary=dictionary)
        rules = load_rules(paths["rules"], roles=roles, dictionary=dictionary, questions=questions)
        prompts = load_prompt_templates(paths["prompts"])
        parametric_knowledge = load_parametric_knowledge(paths["knowledge_base"])
    except (ValueError, KeyError) as exc:
        raise ArtifactConfigurationError("Configured artifacts failed cross-validation") from exc
    actual = ArtifactVersions(
        roles=roles.artifact_version,
        dictionary=dictionary.artifact_version,
        questions=questions.artifact_version,
        rules=rules.artifact_version,
        prompts=prompts.artifact_version,
        knowledge_base=parametric_knowledge.artifact_version,
    )
    if actual != versions:
        raise ArtifactConfigurationError(
            f"Configured artifact versions {versions} do not match loaded versions {actual}"
        )
    if hashes != tuple(
        sorted((key, hashlib.sha256(path.read_bytes()).hexdigest()) for key, path in paths.items())
    ):
        raise ArtifactConfigurationError("Artifact bytes changed while loading")
    return RuntimeArtifacts(
        roles,
        dictionary,
        questions,
        rules,
        prompts,
        parametric_knowledge,
        versions,
        root.resolve(),
        hashes,
    )


def session_runtime_artifacts(defaults: RuntimeArtifacts, session) -> RuntimeArtifacts:
    """Resolve a retained server-side session tuple without changing creation defaults.

    The session has already been fetched in authenticated organization scope. No request
    field, filename, current release or implicit 'latest' is an artifact authority.
    Each return value is immutable and request-local; concurrent L/F requests cannot
    change a shared service's artifacts.
    """
    versions = ArtifactVersions(
        roles=session.role_artifact_version,
        dictionary=session.dictionary_artifact_version,
        questions=session.question_artifact_version,
        rules=session.rules_artifact_version,
        prompts=session.prompt_artifact_version,
        knowledge_base=defaults.versions.knowledge_base,
    )
    if (versions.questions, versions.rules) not in {("1.0.0", "1.0.0"), ("2.0.0", "2.0.0")}:
        raise ArtifactConfigurationError("Unsupported retained session profile")
    if versions == defaults.versions:
        return defaults
    if defaults.source_root is None:
        raise ArtifactConfigurationError("Pinned session artifact source is unavailable")
    return load_runtime_artifacts(defaults.source_root, versions)
