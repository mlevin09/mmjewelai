"""Deterministic Knowledge Library Contract v1.1 compiler and fail-closed validator.

Contract v1.1 keeps the v1 evidence/provenance model intact while expanding policy
targets to the frozen Jewelry Design Schema v1.1 Product State registry.
"""

import hashlib
import json
import unicodedata
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, StringConstraints, model_validator

from .knowledge_library import (
    Claim,
    CompiledClaim,
    CompiledDomainKnowledge,
    CompiledLanguageMapping,
    CompiledSource,
    DomainKnowledge,
    LanguageMapping,
    Lifecycle,
    Source,
    SourceType,
)
from .knowledge_targets_v1_1 import POLICY_TARGET_TEMPLATES_V1_1
from .models import ImmutableModel, Version

KNOWLEDGE_LIBRARY_CONTRACT_VERSION_V1_1 = "1.1.0"
KNOWLEDGE_LIBRARY_SCHEMA_VERSION_V1_1 = "1.1.0"

RecordId = Annotated[str, StringConstraints(min_length=1)]
PolicyTargetV1_1 = Annotated[
    str,
    StringConstraints(
        pattern=(
            r"^[a-z][a-z0-9_]*(?:\.(?:[a-z][a-z0-9_]*|"
            r"\{group_id\}|\{component_id\}|\{element_id\}))*$"
        )
    ),
]


class KnowledgeLibraryV1_1ValidationError(ValueError):
    """Raised when a v1.1 bundle cannot safely compile."""


class PolicyV1_1(ImmutableModel):
    policy_id: RecordId
    target: PolicyTargetV1_1
    effect: Annotated[str, StringConstraints(min_length=1)]
    source_kind: Literal["DOMAIN_KNOWLEDGE", "INTERNAL_PRODUCT_DECISION"]
    source_refs: tuple[RecordId, ...] = Field(min_length=1)
    lifecycle_status: Lifecycle

    @model_validator(mode="after")
    def validate_source_refs(self):
        if len(set(self.source_refs)) != len(self.source_refs):
            raise ValueError("policy source_refs must be unique")
        return self


class KnowledgeLibraryBundleV1_1(ImmutableModel):
    contract_version: Literal["1.1.0"] = KNOWLEDGE_LIBRARY_CONTRACT_VERSION_V1_1
    package_id: Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_.-]+$")]
    artifact_version: Version | None = None
    sources: tuple[Source, ...]
    claims: tuple[Claim, ...]
    domain_knowledge: tuple[DomainKnowledge, ...]
    language_mappings: tuple[LanguageMapping, ...]
    policies: tuple[PolicyV1_1, ...]


class CompiledPolicyV1_1(ImmutableModel):
    policy_id: RecordId
    target: PolicyTargetV1_1
    effect: str
    source_kind: Literal["DOMAIN_KNOWLEDGE", "INTERNAL_PRODUCT_DECISION"]
    source_refs: tuple[RecordId, ...]
    lifecycle_status: Literal["COMPILED"] = "COMPILED"


class CompiledKnowledgeLibraryV1_1(ImmutableModel):
    contract_version: Literal["1.1.0"] = KNOWLEDGE_LIBRARY_CONTRACT_VERSION_V1_1
    schema_version: Literal["1.1.0"] = KNOWLEDGE_LIBRARY_SCHEMA_VERSION_V1_1
    package_id: str
    artifact_version: Version
    active_for_production: Literal[False] = False
    sources: tuple[CompiledSource, ...]
    claims: tuple[CompiledClaim, ...]
    domain_knowledge: tuple[CompiledDomainKnowledge, ...]
    language_mappings: tuple[CompiledLanguageMapping, ...]
    policies: tuple[CompiledPolicyV1_1, ...]

    def canonical_json(self) -> str:
        return json.dumps(
            self.model_dump(mode="json"),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()


class CompilationManifestV1_1(ImmutableModel):
    contract_version: Literal["1.1.0"] = KNOWLEDGE_LIBRARY_CONTRACT_VERSION_V1_1
    schema_version: Literal["1.1.0"] = KNOWLEDGE_LIBRARY_SCHEMA_VERSION_V1_1
    package_id: str
    artifact_version: Version
    active_for_production: Literal[False] = False
    runtime_sha256: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
    source_count: int
    claim_count: int
    domain_count: int
    language_mapping_count: int
    policy_count: int


def _normalize_surface(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def _unique_ids(records, attribute: str, label: str) -> None:
    values = [getattr(record, attribute) for record in records]
    if len(set(values)) != len(values):
        raise KnowledgeLibraryV1_1ValidationError(f"duplicate {label} IDs")


def _record_id_attribute(record) -> str:
    for attribute in ("source_id", "claim_id", "concept_id", "mapping_id", "policy_id"):
        if hasattr(record, attribute):
            return attribute
    raise TypeError(f"unsupported record type: {type(record)!r}")


def _reject_runtime_lifecycle(records, label: str) -> None:
    forbidden = [
        getattr(record, _record_id_attribute(record))
        for record in records
        if record.lifecycle_status in {Lifecycle.COMPILED, Lifecycle.ACTIVE}
    ]
    if forbidden:
        raise KnowledgeLibraryV1_1ValidationError(
            f"{label} input contains runtime lifecycle COMPILED/ACTIVE: {sorted(forbidden)}"
        )


class KnowledgeLibraryRegistryV1_1:
    """Validated immutable source bundle pinned to Contract v1.1.0."""

    def __init__(self, bundle: KnowledgeLibraryBundleV1_1):
        self.bundle = KnowledgeLibraryBundleV1_1.model_validate(bundle)
        self._validate()

    def _validate(self) -> None:
        bundle = self.bundle
        groups = (
            (bundle.sources, "source_id", "source"),
            (bundle.claims, "claim_id", "claim"),
            (bundle.domain_knowledge, "concept_id", "concept"),
            (bundle.language_mappings, "mapping_id", "mapping"),
            (bundle.policies, "policy_id", "policy"),
        )
        for records, attribute, label in groups:
            _unique_ids(records, attribute, label)
            _reject_runtime_lifecycle(records, label)

        sources = {record.source_id: record for record in bundle.sources}
        claims = {record.claim_id: record for record in bundle.claims}
        concepts = {record.concept_id: record for record in bundle.domain_knowledge}

        for claim in bundle.claims:
            for source_id in (claim.source_id, *claim.supporting_source_ids):
                if source_id not in sources:
                    raise KnowledgeLibraryV1_1ValidationError(
                        f"claim {claim.claim_id} references unknown source {source_id}"
                    )

        for concept in bundle.domain_knowledge:
            if concept.parent_id is not None and concept.parent_id not in concepts:
                raise KnowledgeLibraryV1_1ValidationError(
                    f"concept {concept.concept_id} has unknown parent {concept.parent_id}"
                )
            for relationship in concept.relationships:
                if relationship.target_id not in concepts:
                    raise KnowledgeLibraryV1_1ValidationError(
                        f"concept {concept.concept_id} has unknown relationship target "
                        f"{relationship.target_id}"
                    )
            for claim_id in concept.claim_ids:
                if claim_id not in claims:
                    raise KnowledgeLibraryV1_1ValidationError(
                        f"concept {concept.concept_id} references unknown claim {claim_id}"
                    )

        for mapping in bundle.language_mappings:
            if mapping.concept_id not in concepts:
                raise KnowledgeLibraryV1_1ValidationError(
                    f"mapping {mapping.mapping_id} references unknown concept {mapping.concept_id}"
                )

        self._validate_language_collisions()
        self._validate_policies(sources, concepts)

    def _validate_language_collisions(self) -> None:
        surfaces: dict[tuple[str, str | None, str], list[LanguageMapping]] = {}
        for mapping in self.bundle.language_mappings:
            for surface in (mapping.canonical_term, *mapping.aliases):
                key = (mapping.locale, mapping.context, _normalize_surface(surface))
                surfaces.setdefault(key, []).append(mapping)

        for (locale, context, surface), mappings in surfaces.items():
            direct = [item for item in mappings if item.mapping_mode.value == "DIRECT"]
            ambiguous = [item for item in mappings if item.mapping_mode.value == "AMBIGUOUS"]
            if direct and ambiguous:
                raise KnowledgeLibraryV1_1ValidationError(
                    f"DIRECT/AMBIGUOUS collision for {locale}/{context}/{surface!r}"
                )
            resolved = {
                item.concept_id
                for item in mappings
                if item.mapping_mode.value != "AMBIGUOUS"
            }
            if len(resolved) > 1:
                raise KnowledgeLibraryV1_1ValidationError(
                    f"conflicting same-scope alias for {locale}/{context}/{surface!r}"
                )

    def _validate_policies(
        self,
        sources: dict[str, Source],
        concepts: dict[str, DomainKnowledge],
    ) -> None:
        for policy in self.bundle.policies:
            if policy.target not in POLICY_TARGET_TEMPLATES_V1_1:
                raise KnowledgeLibraryV1_1ValidationError(
                    f"policy {policy.policy_id} targets unavailable Design Schema v1.1 field "
                    f"{policy.target}"
                )
            if policy.source_kind == "DOMAIN_KNOWLEDGE":
                missing = [ref for ref in policy.source_refs if ref not in concepts]
            else:
                missing = [
                    ref
                    for ref in policy.source_refs
                    if ref not in sources
                    or sources[ref].source_type != SourceType.INTERNAL_DECISION
                ]
            if missing:
                raise KnowledgeLibraryV1_1ValidationError(
                    f"policy {policy.policy_id} has invalid source refs: {sorted(missing)}"
                )

    def compile(self) -> tuple[CompiledKnowledgeLibraryV1_1, CompilationManifestV1_1]:
        if self.bundle.artifact_version is None:
            raise KnowledgeLibraryV1_1ValidationError(
                "artifact_version is required for deterministic production compilation"
            )

        reviewed_sources = {
            item.source_id: item
            for item in self.bundle.sources
            if item.lifecycle_status == Lifecycle.REVIEWED
        }
        reviewed_claims = {
            item.claim_id: item
            for item in self.bundle.claims
            if item.lifecycle_status == Lifecycle.REVIEWED
        }
        reviewed_concepts = {
            item.concept_id: item
            for item in self.bundle.domain_knowledge
            if item.lifecycle_status == Lifecycle.REVIEWED
        }

        for claim in reviewed_claims.values():
            refs = (claim.source_id, *claim.supporting_source_ids)
            if any(ref not in reviewed_sources for ref in refs):
                raise KnowledgeLibraryV1_1ValidationError(
                    f"reviewed claim {claim.claim_id} depends on non-REVIEWED evidence"
                )

        for concept in reviewed_concepts.values():
            if concept.parent_id is not None and concept.parent_id not in reviewed_concepts:
                raise KnowledgeLibraryV1_1ValidationError(
                    f"reviewed concept {concept.concept_id} depends on non-REVIEWED parent"
                )
            if any(rel.target_id not in reviewed_concepts for rel in concept.relationships):
                raise KnowledgeLibraryV1_1ValidationError(
                    f"reviewed concept {concept.concept_id} depends on non-REVIEWED relationship"
                )
            if any(claim_id not in reviewed_claims for claim_id in concept.claim_ids):
                raise KnowledgeLibraryV1_1ValidationError(
                    f"reviewed concept {concept.concept_id} depends on non-REVIEWED claim"
                )

        reviewed_mappings = [
            item
            for item in self.bundle.language_mappings
            if item.lifecycle_status == Lifecycle.REVIEWED
        ]
        for mapping in reviewed_mappings:
            if mapping.concept_id not in reviewed_concepts:
                raise KnowledgeLibraryV1_1ValidationError(
                    f"reviewed mapping {mapping.mapping_id} depends on non-REVIEWED concept"
                )

        reviewed_policies = [
            item for item in self.bundle.policies if item.lifecycle_status == Lifecycle.REVIEWED
        ]
        for policy in reviewed_policies:
            valid = reviewed_concepts if policy.source_kind == "DOMAIN_KNOWLEDGE" else reviewed_sources
            if any(ref not in valid for ref in policy.source_refs):
                raise KnowledgeLibraryV1_1ValidationError(
                    f"reviewed policy {policy.policy_id} depends on non-REVIEWED provenance"
                )

        runtime = CompiledKnowledgeLibraryV1_1(
            package_id=self.bundle.package_id,
            artifact_version=self.bundle.artifact_version,
            sources=tuple(
                CompiledSource(
                    source_id=item.source_id,
                    title=item.title,
                    source_type=item.source_type,
                    evidence_tier=item.evidence_tier,
                )
                for item in sorted(reviewed_sources.values(), key=lambda item: item.source_id)
            ),
            claims=tuple(
                CompiledClaim(
                    claim_id=item.claim_id,
                    statement=item.statement,
                    source_id=item.source_id,
                    supporting_source_ids=tuple(sorted(item.supporting_source_ids)),
                    evidence_strength=item.evidence_strength,
                )
                for item in sorted(reviewed_claims.values(), key=lambda item: item.claim_id)
            ),
            domain_knowledge=tuple(
                CompiledDomainKnowledge(
                    concept_id=item.concept_id,
                    kind=item.kind,
                    parent_id=item.parent_id,
                    relationships=tuple(
                        sorted(item.relationships, key=lambda rel: (rel.type, rel.target_id))
                    ),
                    claim_ids=tuple(sorted(item.claim_ids)),
                    structural_schema=item.structural_schema,
                )
                for item in sorted(reviewed_concepts.values(), key=lambda item: item.concept_id)
            ),
            language_mappings=tuple(
                CompiledLanguageMapping(
                    mapping_id=item.mapping_id,
                    concept_id=item.concept_id,
                    locale=item.locale,
                    canonical_term=item.canonical_term,
                    aliases=tuple(sorted(item.aliases, key=_normalize_surface)),
                    mapping_mode=item.mapping_mode,
                    mapping_quality=item.mapping_quality,
                    context=item.context,
                )
                for item in sorted(reviewed_mappings, key=lambda item: item.mapping_id)
            ),
            policies=tuple(
                CompiledPolicyV1_1(
                    policy_id=item.policy_id,
                    target=item.target,
                    effect=item.effect,
                    source_kind=item.source_kind,
                    source_refs=tuple(sorted(item.source_refs)),
                )
                for item in sorted(reviewed_policies, key=lambda item: item.policy_id)
            ),
        )
        manifest = CompilationManifestV1_1(
            package_id=runtime.package_id,
            artifact_version=runtime.artifact_version,
            runtime_sha256=runtime.sha256,
            source_count=len(runtime.sources),
            claim_count=len(runtime.claims),
            domain_count=len(runtime.domain_knowledge),
            language_mapping_count=len(runtime.language_mappings),
            policy_count=len(runtime.policies),
        )
        return runtime, manifest


def validate_knowledge_library_v1_1(data: object) -> KnowledgeLibraryRegistryV1_1:
    return KnowledgeLibraryRegistryV1_1(KnowledgeLibraryBundleV1_1.model_validate(data))


def load_knowledge_library_v1_1(path: str | Path) -> KnowledgeLibraryRegistryV1_1:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return validate_knowledge_library_v1_1(data)


def compile_knowledge_library_v1_1(
    bundle: KnowledgeLibraryBundleV1_1 | KnowledgeLibraryRegistryV1_1 | object,
) -> tuple[CompiledKnowledgeLibraryV1_1, CompilationManifestV1_1]:
    registry = (
        bundle
        if isinstance(bundle, KnowledgeLibraryRegistryV1_1)
        else validate_knowledge_library_v1_1(bundle)
    )
    return registry.compile()
