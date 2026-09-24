import json
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest
from jewelai_domain.dictionary import (
    AmbiguousMatch,
    DictionaryCategory,
    DictionaryLocale,
    MatchCandidate,
    MatchKind,
    ResolvedMatch,
    load_domain_dictionary,
)
from jewelai_domain.models import (
    Design,
    DesignRevision,
    MessageSource,
    NotApplicable,
    RevisionEvent,
)
from jsonschema import Draft202012Validator
from pydantic import ValidationError

from jewelai_parser import (
    PARSER_SCHEMA_VERSION,
    ParserCandidate,
    ParserIssueCode,
    ParserWarningCode,
    StaleParserProposalError,
    build_parser_proposal,
)
from jewelai_parser.schema import parser_json_schema

ROOT = Path(__file__).resolve().parents[3]
NOW = datetime(2026, 9, 24, 12, 0, tzinfo=UTC)
SOURCE = MessageSource(message_id="message-1", recorded_at=NOW)


@pytest.fixture(scope="module")
def dictionary():
    return load_domain_dictionary(ROOT / "data" / "dictionary" / "v1.0.0.json")


def revision(design=None):
    return DesignRevision(
        schema_version="1.0.0",
        design_id=UUID("11111111-1111-4111-8111-111111111111"),
        revision_id=UUID("22222222-2222-4222-8222-222222222222"),
        revision=1,
        created_at=NOW,
        event=RevisionEvent(action="create", source=SOURCE, reason="Parser test"),
        design=design or Design(),
    )


def candidate(*updates):
    return ParserCandidate.model_validate({"schema_version": "1.0.0", "updates": updates})


def proposal(current, updates, dictionary, locale="en"):
    return build_parser_proposal(
        current,
        expected_revision_id=current.revision_id,
        source=SOURCE,
        locale=locale,
        dictionary=dictionary,
        candidate=candidate(*updates),
    )


def term(target, text):
    return {"target": target, "value": {"kind": "term", "text": text}}


def test_published_schema_is_current_valid_and_strict():
    generated = parser_json_schema()
    Draft202012Validator.check_schema(generated)
    published = json.loads((ROOT / "specs" / "parser" / "schema.json").read_text())
    assert published == generated
    assert PARSER_SCHEMA_VERSION == "1.0.0"
    assert published["$defs"]["ParserCandidate"]["additionalProperties"] is False


def test_candidate_rejects_unknown_fields_wrong_kinds_and_duplicate_targets():
    with pytest.raises(ValidationError, match="extra_forbidden"):
        ParserCandidate.model_validate(
            {"updates": [{**term("jewelry_type", "ring"), "confirmed": True}]}
        )
    with pytest.raises(ValidationError, match="requires a term candidate"):
        candidate(
            {
                "target": "center_stone.shape",
                "value": {"kind": "weight", "value": {"value": 1.0, "unit": "ct"}},
            }
        )
    with pytest.raises(ValidationError, match="duplicate concrete targets"):
        candidate(term("center_stone.shape", "oval"), term("center_stone.shape", "oval"))
    with pytest.raises(ValidationError):
        candidate(term("center_stone.color", "green"))
    schema = parser_json_schema()
    assert "role_id" not in schema["$defs"]["ParserCandidate"]["properties"]
    assert "role_id" not in schema["$defs"]["ParserProposal"]["properties"]


def test_en_ru_dictionary_resolution_and_semantic_distinctions(dictionary):
    en = proposal(
        revision(),
        [
            term("jewelry_type", "ring"),
            term("center_stone.material", "emerald"),
            term("center_stone.shape", "emerald cut"),
            term("center_stone.cut", "step cut"),
        ],
        dictionary,
    )
    assert en.proposed_design.jewelry_type.value == "ring"
    assert en.proposed_design.center_stone.material.value == "emerald"
    assert en.proposed_design.center_stone.shape.value == "emerald_cut"
    assert en.proposed_design.center_stone.cut.value == "step_cut"
    assert (
        en.proposed_design.center_stone.material.value
        != en.proposed_design.center_stone.shape.value
    )

    ru = proposal(
        revision(),
        [term("jewelry_type", "кольцо"), term("center_stone.material", "изумруд")],
        dictionary,
        locale="ru",
    )
    assert ru.proposed_design.jewelry_type.value == "ring"
    assert ru.proposed_design.center_stone.material.value == "emerald"


def test_proposal_states_are_explicit_unconfirmed_and_unlocked(dictionary):
    result = proposal(revision(), [term("center_stone.shape", "oval")], dictionary)
    state = result.proposed_design.center_stone.shape
    assert state.origin == "explicit"
    assert state.source == SOURCE
    assert not state.confirmed
    assert not state.locked


def test_unsupported_ambiguous_deprecated_alias_and_deprecated_entry(dictionary):
    unsupported = proposal(revision(), [term("center_stone.shape", "hexadecagon")], dictionary)
    assert [issue.code for issue in unsupported.issues] == [ParserIssueCode.UNSUPPORTED_TERM]
    assert not unsupported.has_changes

    alias = proposal(revision(), [term("center_stone.shape", "emerald shape")], dictionary)
    assert alias.proposed_design.center_stone.shape.value == "emerald_cut"
    assert [warning.code for warning in alias.warnings] == [ParserWarningCode.DEPRECATED_ALIAS_USED]

    class StubRegistry:
        artifact_version = "1.0.0"

        def __init__(self, outcome):
            self.outcome = outcome

        def normalize(self, *_, **__):
            return self.outcome

    candidates = tuple(
        MatchCandidate(
            domain_id=value,
            category=DictionaryCategory.STONE_SHAPE,
            canonical_term=value,
            matched_via=MatchKind.SYNONYM,
            deprecated_input=False,
            entry_deprecated=False,
        )
        for value in ("oval", "emerald_cut")
    )
    ambiguous = proposal(
        revision(),
        [term("center_stone.shape", "shared")],
        StubRegistry(
            AmbiguousMatch(
                normalized_term="shared", locale=DictionaryLocale.EN, candidates=candidates
            )
        ),
    )
    assert ambiguous.issues[0].code == ParserIssueCode.AMBIGUOUS_TERM
    assert ambiguous.issues[0].candidates == candidates
    assert ambiguous.proposed_design == Design()
    assert not ambiguous.has_changes

    deprecated_candidate = candidates[0].model_copy(
        update={"entry_deprecated": True, "replaced_by": "emerald_cut"}
    )
    deprecated = proposal(
        revision(),
        [term("center_stone.shape", "old")],
        StubRegistry(
            ResolvedMatch(
                normalized_term="old",
                locale=DictionaryLocale.EN,
                candidate=deprecated_candidate,
            )
        ),
    )
    assert deprecated.issues[0].code == ParserIssueCode.DEPRECATED_ENTRY


def test_locked_values_are_preserved_and_equal_values_are_noops(dictionary):
    current = DesignRevision.model_validate_json(
        (ROOT / "specs" / "jewelry-design-schema" / "fixtures" / "valid" / "ring.json").read_text()
    )
    changed = proposal(current, [term("metal.color", "yellow")], dictionary)
    assert changed.proposed_design.metal.color.value == "white"
    assert changed.issues[0].code == ParserIssueCode.LOCKED_FIELD_CONFLICT
    same = proposal(current, [term("metal.color", "white")], dictionary)
    assert not same.issues
    assert not same.has_changes
    assert same.proposed_design == current.design


def test_not_applicable_field_cannot_be_silently_replaced(dictionary):
    original_source = MessageSource(message_id="not-applicable", recorded_at=NOW)
    original = NotApplicable(
        reason="The design intentionally has no center stone shape.",
        source=original_source,
        locked=True,
    )
    current = revision(Design(center_stone={"shape": original}))

    result = proposal(current, [term("center_stone.shape", "oval")], dictionary)

    assert [issue.code for issue in result.issues] == [ParserIssueCode.NOT_APPLICABLE_CONFLICT]
    assert not result.has_changes
    assert not result.accepted_updates
    assert isinstance(result.proposed_design.center_stone.shape, NotApplicable)
    assert result.proposed_design.center_stone.shape == original
    assert result.proposed_design.center_stone.shape.source == original_source
    assert result.proposed_design.center_stone.shape.confirmed
    assert result.proposed_design.center_stone.shape.locked
    assert result.proposed_design.center_stone.shape.origin == "explicit"


def test_not_applicable_conflict_does_not_block_unrelated_update_and_is_deterministic(
    dictionary,
):
    original = NotApplicable(
        reason="The design intentionally has no center stone shape.",
        source=MessageSource(message_id="not-applicable", recorded_at=NOW),
    )
    current = revision(Design(center_stone={"shape": original}))
    updates = [term("jewelry_type", "ring"), term("center_stone.shape", "oval")]

    first = proposal(current, updates, dictionary)
    second = proposal(current, list(reversed(updates)), dictionary)

    assert first == second
    assert first.proposed_design.center_stone.shape == original
    assert first.proposed_design.jewelry_type.value == "ring"
    assert [item.concrete_target for item in first.accepted_updates] == ["jewelry_type"]
    assert [issue.code for issue in first.issues] == [ParserIssueCode.NOT_APPLICABLE_CONFLICT]


@pytest.mark.parametrize("origin", ["unknown", "explicit", "derived", "assumed"])
def test_unlocked_unknown_derived_and_assumed_values_can_be_proposed_over(origin, dictionary):
    data = Design().model_dump(mode="json")
    if origin == "unknown":
        state = {"availability": "unknown", "origin": "unknown"}
    elif origin == "explicit":
        state = {
            "availability": "value",
            "origin": "explicit",
            "value": "round",
            "source": SOURCE.model_dump(mode="json"),
            "confirmed": True,
            "locked": False,
        }
    elif origin == "derived":
        state = {
            "availability": "value",
            "origin": "derived",
            "value": "round",
            "sources": [
                {
                    "kind": "knowledge",
                    "record_id": "record",
                    "version": "1.0.0",
                    "recorded_at": NOW.isoformat(),
                }
            ],
            "uncertainty": "Test-only source",
        }
    else:
        state = {
            "availability": "value",
            "origin": "assumed",
            "value": "round",
            "source": {
                "kind": "rule",
                "rule_id": "test_rule",
                "version": "1.0.0",
                "recorded_at": NOW.isoformat(),
            },
            "rationale": "Test-only assumption",
        }
    data["center_stone"]["shape"] = state
    result = proposal(
        revision(Design.model_validate(data)),
        [term("center_stone.shape", "oval")],
        dictionary,
    )
    assert result.proposed_design.center_stone.shape.origin == "explicit"
    assert result.proposed_design.center_stone.shape.value == "oval"
    assert result.proposed_design.center_stone.shape.source == SOURCE
    assert not result.proposed_design.center_stone.shape.confirmed


def test_typed_numeric_candidates_and_no_dimension_inference(dictionary):
    result = proposal(
        revision(),
        [
            term("center_stone.material", "emerald"),
            {
                "target": "center_stone.weight",
                "value": {"kind": "weight", "value": {"value": 3.0, "unit": "ct"}},
            },
            {
                "target": "center_stone.dimensions",
                "value": {
                    "kind": "dimensions",
                    "value": {
                        "length": {"value": 9.0, "unit": "mm"},
                        "width": {"value": 7.0, "unit": "mm"},
                        "depth": {"value": 4.5, "unit": "mm"},
                    },
                },
            },
            {
                "target": "metal.purity",
                "value": {"kind": "purity", "value": {"value": 18.0, "unit": "karat"}},
            },
        ],
        dictionary,
    )
    assert result.proposed_design.center_stone.weight.value.value == 3.0
    assert result.proposed_design.center_stone.dimensions.value.length.value == 9.0
    assert result.proposed_design.metal.purity.value.value == 18.0

    no_dimensions = proposal(
        revision(),
        [
            term("center_stone.material", "emerald"),
            {
                "target": "center_stone.weight",
                "value": {"kind": "weight", "value": {"value": 3.0, "unit": "ct"}},
            },
        ],
        dictionary,
    )
    assert no_dimensions.proposed_design.center_stone.dimensions is None
    with pytest.raises(ValidationError):
        candidate(
            {
                "target": "center_stone.weight",
                "value": {"kind": "weight", "value": {"value": -1.0, "unit": "ct"}},
            }
        )


@pytest.mark.parametrize(
    "update",
    [
        {
            "target": "center_stone.dimensions",
            "value": {
                "kind": "dimensions",
                "value": {
                    "length": {"value": 0.0, "unit": "mm"},
                    "width": {"value": 7.0, "unit": "mm"},
                    "depth": {"value": 4.0, "unit": "mm"},
                },
            },
        },
        {
            "target": "metal.purity",
            "value": {"kind": "purity", "value": {"value": 25.0, "unit": "karat"}},
        },
        {
            "target": "side_stones[*].quantity",
            "group_id": "accents",
            "value": {"kind": "quantity", "value": {"value": 0, "scope": "per_side"}},
        },
    ],
)
def test_invalid_typed_numeric_candidates_are_rejected(update):
    with pytest.raises(ValidationError):
        candidate(update)


def test_side_stone_quantity_requires_existing_stable_group(dictionary):
    fixture = json.loads(
        (ROOT / "specs" / "jewelry-design-schema" / "fixtures" / "valid" / "ring.json").read_text()
    )
    current = DesignRevision.model_validate(fixture)
    update = {
        "target": "side_stones[*].quantity",
        "group_id": "accents",
        "value": {"kind": "quantity", "value": {"value": 6, "scope": "per_pair"}},
    }
    result = proposal(current, [update], dictionary)
    assert result.accepted_updates[0].concrete_target == "side_stones.accents.quantity"
    assert result.proposed_design.side_stones[0].quantity.value.scope == "per_pair"

    missing = deepcopy(update)
    missing["group_id"] = "missing_group"
    result = proposal(current, [missing], dictionary)
    assert result.issues[0].code == ParserIssueCode.UNKNOWN_SIDE_STONE_GROUP


def test_proposals_are_stable_sorted_and_omissions_preserve_state(dictionary):
    updates = [term("center_stone.shape", "oval"), term("jewelry_type", "ring")]
    first = proposal(revision(), updates, dictionary)
    second = proposal(revision(), list(reversed(updates)), dictionary)
    assert first == second
    assert [item.concrete_target for item in first.accepted_updates] == [
        "center_stone.shape",
        "jewelry_type",
    ]
    assert first.proposed_design.metal == Design().metal


def test_stale_revision_is_rejected_before_proposal_building(dictionary):
    current = revision()
    with pytest.raises(StaleParserProposalError):
        build_parser_proposal(
            current,
            expected_revision_id=UUID("33333333-3333-4333-8333-333333333333"),
            source=SOURCE,
            locale="en",
            dictionary=dictionary,
            candidate=candidate(),
        )
