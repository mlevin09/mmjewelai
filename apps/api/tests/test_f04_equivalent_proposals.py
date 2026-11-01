"""Typed ParserProposal/Matrix tests, not persisted F-profile HTTP acceptance."""

import pytest
from jewelai_domain.models import DesignRevision, MessageSource
from jewelai_parser import parse_full_message
from test_parsed_enrichment import (
    NOW,
)
from test_parsed_enrichment import (
    collision_release as collision_release,
)
from test_parsed_enrichment import (
    dictionary as dictionary,
)
from test_parsed_enrichment import (
    ring as ring,
)
from test_parsed_enrichment import (
    templates as templates,
)

from jewelai_api.parsed_enrichment import (
    ParsedEnrichmentInputError,
    enrich_parsed_candidates_with_active_release,
)


def evaluate(text, revision, dictionary, templates, release, recognition, *, group=None):
    store, stored, compiled, report, active = release
    parsed = parse_full_message(
        text,
        locale="en",
        dictionary=dictionary,
        knowledge_runtime=compiled if recognition else None,
    )
    ids = tuple(
        c.candidate_id
        for c in parsed.candidates
        if c.target == "metal.material" and c.normalization_source == "domain_dictionary"
    )
    result = enrich_parsed_candidates_with_active_release(
        revision,
        parse_result=parsed,
        source=MessageSource(message_id="typed-f04-test", recorded_at=NOW),
        dictionary=dictionary,
        templates=templates,
        artifact_store=store,
        knowledge_package_id=stored.package_id,
        knowledge_artifact_version=stored.artifact_version,
        active_release=active,
        validation_report=report,
        equivalent_candidate_ids=ids if group is None else group,
    )
    return parsed, result


@pytest.mark.parametrize("recognition", (False, True))
def test_equivalent_sources_yield_one_material_proposal_without_mutating_revision(
    ring,
    dictionary,
    templates,
    collision_release,
    recognition,
):
    data = ring.model_dump(mode="json")
    data["design"] = {}
    revision = DesignRevision.model_validate(data)
    before = revision.model_dump_json()
    parsed, result = evaluate(
        "A gold ring with gold metal.",
        revision,
        dictionary,
        templates,
        collision_release,
        recognition,
    )
    accepted = [
        u for u in result.parser_proposal.accepted_updates if u.concrete_target == "metal.material"
    ]
    assert len(accepted) == 1 and accepted[0].canonical_value == "gold"
    assert tuple(d.candidate for d in result.dispositions) == parsed.candidates
    assert result.parser_proposal.proposed_design.metal.material.value == "gold"
    assert result.parser_proposal.proposed_design.center_stone == revision.design.center_stone
    assert revision.model_dump_json() == before


def test_conflicting_values_cannot_claim_equivalence(
    ring, dictionary, templates, collision_release
):
    with pytest.raises(ParsedEnrichmentInputError, match="explicit value"):
        evaluate("Gold and platinum ring.", ring, dictionary, templates, collision_release, False)


def test_foreign_or_missing_source_id_cannot_claim_equivalence(
    ring, dictionary, templates, collision_release
):
    with pytest.raises(ParsedEnrichmentInputError, match="eligible material group"):
        evaluate(
            "Gold gold ring.",
            ring,
            dictionary,
            templates,
            collision_release,
            False,
            group=("candidate_0001", "foreign-candidate"),
        )


def test_equivalence_cannot_bypass_locked_material(ring, dictionary, templates, collision_release):
    data = ring.model_dump(mode="json")
    data["design"]["metal"]["material"]["locked"] = True
    revision = DesignRevision.model_validate(data)
    before = revision.model_dump_json()
    _, result = evaluate(
        "Platinum platinum ring.", revision, dictionary, templates, collision_release, False
    )
    assert not any(
        u.concrete_target == "metal.material" for u in result.parser_proposal.accepted_updates
    )
    assert result.parser_proposal.proposed_design.metal.material == revision.design.metal.material
    assert revision.model_dump_json() == before
