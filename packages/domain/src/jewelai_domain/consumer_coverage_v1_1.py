"""Schema v1.1 consumer coverage and controlled-adoption gate.

Coverage distinguishes lossless preservation from direct semantic interaction.
A consumer may safely preserve a v1.1 target without yet being able to parse,
ask about, or apply rules to that target.
"""

from typing import Literal

from pydantic import Field

from .knowledge_targets_v1_1 import PRODUCT_STATE_TARGET_FAMILIES_V1_1
from .models import DesignRevision, ImmutableModel
from .models_v1_1 import DesignRevisionV1_1, validate_design_revision

CONSUMER_COVERAGE_VERSION_V1_1 = "1.0.0"

_PARSER_DIRECT = frozenset(
    {
        "jewelry_type",
        "metal.material",
        "metal.color",
        "metal.purity",
        "center_stone.material",
        "center_stone.shape",
        "center_stone.cut",
        "center_stone.weight",
        "center_stone.dimensions",
        "center_stone.setting",
        "style",
        "side_stones.{group_id}.quantity",
    }
)

_QUESTION_DIRECT = frozenset(
    {
        "center_stone.shape",
        "center_stone.dimensions",
        "center_stone.setting",
        "metal.color",
        "side_stones.{group_id}.quantity",
    }
)

_RULES_DIRECT = _QUESTION_DIRECT


class TargetConsumerCoverage(ImmutableModel):
    target_family: str
    state_preservation: Literal[True] = True
    knowledge_runtime: Literal[True] = True
    prompt_compiler: Literal[True] = True
    parser_direct: bool
    question_direct: bool
    rules_direct: bool


class SchemaV1_1ConsumerCoverage(ImmutableModel):
    coverage_version: Literal["1.0.0"] = CONSUMER_COVERAGE_VERSION_V1_1
    design_schema_version: Literal["1.1.0"] = "1.1.0"
    targets: tuple[TargetConsumerCoverage, ...] = Field(min_length=1)

    @property
    def target_count(self) -> int:
        return len(self.targets)

    @property
    def parser_direct_count(self) -> int:
        return sum(item.parser_direct for item in self.targets)

    @property
    def question_direct_count(self) -> int:
        return sum(item.question_direct for item in self.targets)

    @property
    def rules_direct_count(self) -> int:
        return sum(item.rules_direct for item in self.targets)


class SchemaV1_1MigrationEligibility(ImmutableModel):
    coverage_version: Literal["1.0.0"] = CONSUMER_COVERAGE_VERSION_V1_1
    from_schema_version: str
    to_schema_version: Literal["1.1.0"] = "1.1.0"
    eligible: bool
    blockers: tuple[str, ...] = ()
    target_count: int
    preservation_coverage_count: int
    parser_direct_count: int
    question_direct_count: int
    rules_direct_count: int


def build_schema_v1_1_consumer_coverage() -> SchemaV1_1ConsumerCoverage:
    targets = tuple(
        TargetConsumerCoverage(
            target_family=target,
            parser_direct=target in _PARSER_DIRECT,
            question_direct=target in _QUESTION_DIRECT,
            rules_direct=target in _RULES_DIRECT,
        )
        for target in sorted(PRODUCT_STATE_TARGET_FAMILIES_V1_1)
    )
    return SchemaV1_1ConsumerCoverage(targets=targets)


def assess_schema_v1_1_migration_eligibility(
    revision: DesignRevision | DesignRevisionV1_1 | object,
) -> SchemaV1_1MigrationEligibility:
    revision = validate_design_revision(revision)
    coverage = build_schema_v1_1_consumer_coverage()
    blockers: list[str] = []

    if not isinstance(revision, DesignRevision):
        blockers.append("CURRENT_REVISION_IS_NOT_SCHEMA_V1_0")

    preservation_count = sum(
        item.state_preservation and item.knowledge_runtime and item.prompt_compiler
        for item in coverage.targets
    )
    if preservation_count != coverage.target_count:
        blockers.append("INCOMPLETE_V1_1_PRESERVATION_COVERAGE")

    # The current deterministic intake workflow requires these five semantic
    # question/rule targets. Migration is blocked if any of them loses direct support.
    for target in sorted(_QUESTION_DIRECT):
        item = next(entry for entry in coverage.targets if entry.target_family == target)
        if not item.question_direct or not item.rules_direct:
            blockers.append(f"MISSING_BASE_INTERACTION_SUPPORT:{target}")

    return SchemaV1_1MigrationEligibility(
        from_schema_version=revision.schema_version,
        eligible=not blockers,
        blockers=tuple(blockers),
        target_count=coverage.target_count,
        preservation_coverage_count=preservation_count,
        parser_direct_count=coverage.parser_direct_count,
        question_direct_count=coverage.question_direct_count,
        rules_direct_count=coverage.rules_direct_count,
    )
