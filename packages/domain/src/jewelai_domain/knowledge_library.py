"""Deterministic Knowledge Library Contract v1 compiler and fail-closed validator."""

import hashlib
import json
import unicodedata
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, StringConstraints, model_validator

from .models import ImmutableModel, Version

KNOWLEDGE_LIBRARY_CONTRACT_VERSION = "1.0.0"
KNOWLEDGE_LIBRARY_SCHEMA_VERSION = "1.0.0"

ConceptId = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_.]*$")]
RecordId = Annotated[str, StringConstraints(min_length=1)]
PolicyTarget = Annotated[
    str,
    StringConstraints(pattern=r"^[a-z][a-z0-9_]*(?:\.(?:[a-z][a-z0-9_]*|\{group_id\}))*$"),
]


class KnowledgeLibraryValidationError(ValueError):
    """Raised when a bundle cannot safely compile under the frozen contract."""


class Lifecycle(StrEnum):
    DRAFT = "DRAFT"
    REVIEWED = "REVIEWED"
    COMPILED = "COMPILED"
    ACTIVE = "ACTIVE"
    DEPRECATED = "DEPRECATED"
    REJECTED = "REJECTED"


class SourceType(StrEnum):
    STANDARD = "STANDARD"
    OFFICIAL_BODY = "OFFICIAL_BODY"
    PROFESSIONAL_EDUCATION = "PROFESSIONAL_EDUCATION"
    TECHNICAL_MANUFACTURER = "TECHNICAL_MANUFACTURER"
    RETAIL_SECONDARY = "RETAIL_SECONDARY"
    INTERNAL_DECISION = "INTERNAL_DECISION"
    STRUCTURAL_SCHEMA = "STRUCTURAL_SCHEMA"


class EvidenceTier(StrEnum):
    PRIMARY = "PRIMARY"
    SECONDARY = "SECONDARY"
    CORROBORATIVE = "CORROBORATIVE"
    INTERNAL = "INTERNAL"
    STRUCTURAL = "STRUCTURAL"


class EvidenceStrength(StrEnum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    STRUCTURAL = "STRUCTURAL"


class MappingMode(StrEnum):
    DIRECT = "DIRECT"
    CONTEXTUAL = "CONTEXTUAL"
    INPUT_ONLY = "INPUT_ONLY"
    AMBIGUOUS = "AMBIGUOUS"


class MappingQuality(StrEnum):
    EXACT = "EXACT"
    PREFERRED = "PREFERRED"
    CONTEXT_DEPENDENT = "CONTEXT_DEPENDENT"
    APPROXIMATE = "APPROXIMATE"
    NO_DIRECT_EQUIVALENT = "NO_DIRECT_EQUIVALENT"


class Source(ImmutableModel):
    source_id: RecordId
    title: Annotated[str, StringConstraints(min_length=1)]
    source_type: SourceType
    uri: str | None = None
    language: Literal["en", "ru", "mixed", "not_applicable"] | None = None
    jurisdiction: str | None = None
    evidence_tier: EvidenceTier
    lifecycle_status: Lifecycle


class Claim(ImmutableModel):
    claim_id: RecordId
    statement: Annotated[str, StringConstraints(min_length=1)]
    source_id: RecordId
    supporting_source_ids: tuple[RecordId, ...] = ()
    evidence_strength: EvidenceStrength
    scope: str | None = None
    lifecycle_status: Lifecycle

    @model_validator(mode="after")
    def validate_supporting_sources(self):
        if len(set(self.supporting_source_ids)) != len(self.supporting_source_ids):
            raise ValueError("supporting_source_ids must be unique")
        if self.source_id in self.supporting_source_ids:
            raise ValueError("primary source cannot also be a supporting source")
        return self


class Relationship(ImmutableModel):
    type: Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]*$")]
    target_id: ConceptId


class DomainKnowledge(ImmutableModel):
    concept_id: ConceptId
    kind: Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]*$")]
    parent_id: ConceptId | None = None
    relationships: tuple[Relationship, ...] = ()
    claim_ids: tuple[RecordId, ...]
    structural_schema: bool
    lifecycle_status: Lifecycle

    @model_validator(mode="after")
    def validate_evidence_shape(self):
        if len(set(self.claim_ids)) != len(self.claim_ids):
            raise ValueError("claim_ids must be unique")
        if not self.structural_schema and not self.claim_ids:
            raise ValueError("non-structural domain knowledge requires at least one claim")
        return self


class LanguageMapping(ImmutableModel):
    mapping_id: RecordId
    concept_id: ConceptId
    locale: Literal["en", "ru"]
    canonical_term: Annotated[str, StringConstraints(min_length=1)]
    aliases: tuple[Annotated[str, StringConstraints(min_length=1)], ...] = ()
    mapping_mode: MappingMode
    mapping_quality: MappingQuality
    context: str | None = None
    lifecycle_status: Lifecycle

    @model_validator(mode="after")
    def validate_aliases(self):
        normalized = [_normalize_surface(self.canonical_term)]
        normalized.extend(_normalize_surface(alias) for alias in self.aliases)
        if len(set(normalized)) != len(normalized):
            raise ValueError("language mapping surfaces must be unique after normalization")
        return self


class Policy(ImmutableModel):
    policy_id: RecordId
    target: PolicyTarget
    effect: Annotated[str, StringConstraints(min_length=1)]
    source_kind: Literal["DOMAIN_KNOWLEDGE", "INTERNAL_PRODUCT_DECISION"]
    source_refs: tuple[RecordId, ...] = Field(min_length=1)
    lifecycle_status: Lifecycle

    @model_validator(mode="after")
    def validate_source_refs(self):
        if len(set(self.source_refs)) != len(self.source_refs):
            raise ValueError("policy source_refs must be unique")
        return self


class KnowledgeLibraryBundle(ImmutableModel):
    contract_version: Literal["1.0.0"]
    package_id: Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_.-]+$")]
    artifact_version: Version | None = None
    sources: tuple[Source, ...]
    claims: tuple[Claim, ...]
    domain_knowledge: tuple[DomainKnowledge, ...]
    language_mappings: tuple[LanguageMapping, ...]
    policies: tuple[Policy, ...]


class CompiledSource(ImmutableModel):
    source_id: RecordId
    title: str
    source_type: SourceType
    evidence_tier: EvidenceTier
    lifecycle_status: Literal["COMPILED"] = "COMPILED"


class CompiledClaim(ImmutableModel):
    claim_id: RecordId
    statement: str
    source_id: RecordId
    supporting_source_ids: tuple[RecordId, ...]
    evidence_strength: EvidenceStrength
    lifecycle_status: Literal["COMPILED"] = "COMPILED"


class CompiledDomainKnowledge(ImmutableModel):
    concept_id: ConceptId
    kind: str
    parent_id: ConceptId | None
    relationships: tuple[Relationship, ...]
    claim_ids: tuple[RecordId, ...]
    structural_schema: bool
    lifecycle_status: Literal["COMPILED"] = "COMPILED"


class CompiledLanguageMapping(ImmutableModel):
    mapping_id: RecordId
    concept_id: ConceptId
    locale: Literal["en", "ru"]
    canonical_term: str
    aliases: tuple[str, ...]
    mapping_mode: MappingMode
    mapping_quality: MappingQuality
    context: str | None
    lifecycle_status: Literal["COMPILED"] = "COMPILED"


class CompiledPolicy(ImmutableModel):
    policy_id: RecordId
    target: PolicyTarget
    effect: str
    source_kind: Literal["DOMAIN_KNOWLEDGE", "INTERNAL_PRODUCT_DECISION"]
    source_refs: tuple[RecordId, ...]
    lifecycle_status: Literal["COMPILED"] = "COMPILED"


class CompiledKnowledgeLibrary(ImmutableModel):
    contract_version: Literal["1.0.0"] = KNOWLEDGE_LIBRARY_CONTRACT_VERSION
    schema_version: Literal["1.0.0"] = KNOWLEDGE_LIBRARY_SCHEMA_VERSION
    package_id: str
    artifact_version: Version
    active_for_production: Literal[False] = False
    sources: tuple[CompiledSource, ...]
    claims: tuple[CompiledClaim, ...]
    domain_knowledge: tuple[CompiledDomainKnowledge, ...]
    language_mappings: tuple[CompiledLanguageMapping, ...]
    policies: tuple[CompiledPolicy, ...]

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


class CompilationManifest(ImmutableModel):
    contract_version: Literal["1.0.0"] = KNOWLEDGE_LIBRARY_CONTRACT_VERSION
    schema_version: Literal["1.0.0"] = KNOWLEDGE_LIBRARY_SCHEMA_VERSION
    package_id: str
    artifact_version: Version
    active_for_production: Literal[False] = False
    runtime_sha256: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
    source_count: int
    claim_count: int
    domain_count: int
    language_mapping_count: int
    policy_count: int


_SCALAR_POLICY_TARGETS = frozenset(
    {
        "jewelry_type",
        "metal.material",
        "metal.color",
        "metal.purity",
        "metal.finish",
        "center_stone.material",
        "center_stone.shape",
        "center_stone.cut",
        "center_stone.weight",
        "center_stone.dimensions",
        "center_stone.color",
        "center_stone.setting",
        "center_stone.orientation",
        "construction.shank",
        "construction.gallery",
        "construction.basket",
        "construction.clasp",
        "construction.setting_height",
        "construction.shank_width",
        "construction.thickness",
        "style",
    }
)
_COLLECTION_POLICY_TARGETS = frozenset(
    {
        "side_stones.{group_id}.stones.material",
        "side_stones.{group_id}.stones.shape",
        "side_stones.{group_id}.stones.cut",
        "side_stones.{group_id}.stones.weight",
        "side_stones.{group_id}.stones.dimensions",
        "side_stones.{group_id}.stones.color",
        "side_stones.{group_id}.stones.setting",
        "side_stones.{group_id}.stones.orientation",
        "side_stones.{group_id}.quantity",
    }
)
_ALLOWED_POLICY_TARGETS = _SCALAR_POLICY_TARGETS | _COLLECTION_POLICY_TARGETS


def _normalize_surface(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def _unique_ids(records, attribute: str, label: str) -> None:
    values = [getattr(record, attribute) for record in records]
    if len(set(values)) != len(values):
        raise KnowledgeLibraryValidationError(f"duplicate {label} IDs")


def _reject_runtime_lifecycle(records, label: str) -> None:
    forbidden = [
        getattr(record, _record_id_attribute(record))
        for record in records
        if record.lifecycle_status in {Lifecycle.COMPILED, Lifecycle.ACTIVE}
    ]
    if forbidden:
        raise KnowledgeLibraryValidationError(
            f"{label} input contains runtime lifecycle COMPILED/ACTIVE: {sorted(forbidden)}"
        )


def _record_id_attribute(record) -> str:
    for attribute in ("source_id", "claim_id", "concept_id", "mapping_id", "policy_id"):
        if hasattr(record, attribute):
            return attribute
    raise TypeError(f"unsupported record type: {type(record)!r}")


class KnowledgeLibraryRegistry:
    """Validated immutable source bundle pinned to Contract v1.0.0."""

    def __init__(self, bundle: KnowledgeLibraryBundle):
        self.bundle = KnowledgeLibraryBundle.model_validate(bundle)
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
                    raise KnowledgeLibraryValidationError(
                        f"claim {claim.claim_id} references unknown source {source_id}"
                    )

        for concept in bundle.domain_knowledge:
            if concept.parent_id is not None and concept.parent_id not in concepts:
                raise KnowledgeLibraryValidationError(
                    f"concept {concept.concept_id} has unknown parent {concept.parent_id}"
                )
            for relationship in concept.relationships:
                if relationship.target_id not in concepts:
                    raise KnowledgeLibraryValidationError(
                        f"concept {concept.concept_id} has unknown relationship target "
                        f"{relationship.target_id}"
                    )
            for claim_id in concept.claim_ids:
                if claim_id not in claims:
                    raise KnowledgeLibraryValidationError(
                        f"concept {concept.concept_id} references unknown claim {claim_id}"
                    )

        for mapping in bundle.language_mappings:
            if mapping.concept_id not in concepts:
                raise KnowledgeLibraryValidationError(
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
            direct = [item for item in mappings if item.mapping_mode == MappingMode.DIRECT]
            ambiguous = [item for item in mappings if item.mapping_mode == MappingMode.AMBIGUOUS]
            if direct and ambiguous:
                raise KnowledgeLibraryValidationError(
                    f"DIRECT/AMBIGUOUS collision for {locale}/{context}/{surface!r}"
                )

            resolved_concepts = {
                item.concept_id for item in mappings if item.mapping_mode != MappingMode.AMBIGUOUS
            }
            if len(resolved_concepts) > 1:
                raise KnowledgeLibraryValidationError(
                    f"conflicting same-scope alias for {locale}/{context}/{surface!r}"
                )

    def _validate_policies(
        self,
        sources: dict[str, Source],
        concepts: dict[str, DomainKnowledge],
    ) -> None:
        for policy in self.bundle.policies:
            if policy.target not in _ALLOWED_POLICY_TARGETS:
                raise KnowledgeLibraryValidationError(
                    f"policy {policy.policy_id} targets unavailable Design Schema v1 field "
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
                raise KnowledgeLibraryValidationError(
                    f"policy {policy.policy_id} has invalid source refs: {sorted(missing)}"
                )

    def compile(self) -> tuple[CompiledKnowledgeLibrary, CompilationManifest]:
        if self.bundle.artifact_version is None:
            raise KnowledgeLibraryValidationError(
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
                raise KnowledgeLibraryValidationError(
                    f"reviewed claim {claim.claim_id} depends on non-REVIEWED evidence"
                )

        for concept in reviewed_concepts.values():
            if concept.parent_id is not None and concept.parent_id not in reviewed_concepts:
                raise KnowledgeLibraryValidationError(
                    f"reviewed concept {concept.concept_id} depends on non-REVIEWED parent"
                )
            if any(rel.target_id not in reviewed_concepts for rel in concept.relationships):
                raise KnowledgeLibraryValidationError(
                    f"reviewed concept {concept.concept_id} depends on non-REVIEWED relationship"
                )
            if any(claim_id not in reviewed_claims for claim_id in concept.claim_ids):
                raise KnowledgeLibraryValidationError(
                    f"reviewed concept {concept.concept_id} depends on non-REVIEWED claim"
                )

        reviewed_mappings = [
            item
            for item in self.bundle.language_mappings
            if item.lifecycle_status == Lifecycle.REVIEWED
        ]
        for mapping in reviewed_mappings:
            if mapping.concept_id not in reviewed_concepts:
                raise KnowledgeLibraryValidationError(
                    f"reviewed mapping {mapping.mapping_id} depends on non-REVIEWED concept"
                )

        reviewed_policies = [
            item for item in self.bundle.policies if item.lifecycle_status == Lifecycle.REVIEWED
        ]
        for policy in reviewed_policies:
            if policy.source_kind == "DOMAIN_KNOWLEDGE":
                valid = reviewed_concepts
            else:
                valid = reviewed_sources
            if any(ref not in valid for ref in policy.source_refs):
                raise KnowledgeLibraryValidationError(
                    f"reviewed policy {policy.policy_id} depends on non-REVIEWED provenance"
                )

        runtime = CompiledKnowledgeLibrary(
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
                CompiledPolicy(
                    policy_id=item.policy_id,
                    target=item.target,
                    effect=item.effect,
                    source_kind=item.source_kind,
                    source_refs=tuple(sorted(item.source_refs)),
                )
                for item in sorted(reviewed_policies, key=lambda item: item.policy_id)
            ),
        )
        manifest = CompilationManifest(
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


def validate_knowledge_library(data: object) -> KnowledgeLibraryRegistry:
    """Validate one source bundle against the frozen record and semantic contract."""
    return KnowledgeLibraryRegistry(KnowledgeLibraryBundle.model_validate(data))


def load_knowledge_library(path: str | Path) -> KnowledgeLibraryRegistry:
    """Load a JSON bundle from an explicit path and validate it fail-closed."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return validate_knowledge_library(data)


def compile_knowledge_library(
    bundle: KnowledgeLibraryBundle | KnowledgeLibraryRegistry | object,
) -> tuple[CompiledKnowledgeLibrary, CompilationManifest]:
    """Compile REVIEWED inputs deterministically; never emit ACTIVE records."""
    registry = (
        bundle
        if isinstance(bundle, KnowledgeLibraryRegistry)
        else validate_knowledge_library(bundle)
    )
    return registry.compile()
