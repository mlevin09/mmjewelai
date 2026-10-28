"""Original 1.2 histories must restore without rewrite, recompilation, or new authority."""

import hashlib
import json
from copy import deepcopy
from uuid import UUID

import pytest
from jewelai_domain.models_v1_1 import validate_design_revision
from jewelai_persistence.models import (
    ClarificationAnswerRow,
    EnrichmentCycleRow,
    SpecificationRevisionRow,
    UserCorrectionRow,
)
from jewelai_prompts import (
    PromptEnrichmentResult,
    StructuredPromptEnrichmentResult,
    compile_prompt,
    decode_prompt_enrichment_result,
)
from jewelai_prompts.historical_validation import validate_historical_compiled_source
from sqlalchemy import select
from test_effective_readiness import _answer, _correct
from test_effective_readiness import ready_session as ready_session
from test_generation_preparations import post


def historical_result(result, revision, templates):
    """Reproduce the ORIGINAL writer in tests only, never migrate/rewrite a retained payload."""
    payload = result.model_dump(mode="json", exclude={"content_hash"})
    for field in (
        "specification_entries",
        "locked_constraints",
        "disclosures",
        "prompt_template_artifact_version",
    ):
        payload.pop(field)
    payload["enrichment_version"] = "1.2.0"
    payload["compiled_prompt"] = compile_prompt(revision, templates).model_dump(mode="json")
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return PromptEnrichmentResult(
        **payload, content_hash=hashlib.sha256(canonical.encode()).hexdigest()
    )


def test_nested_historical_answers_corrections_and_cycles_remain_original(
    ready_session, engine, monkeypatch
):
    import jewelai_api.parsed_enrichment as parsed
    import jewelai_api.prompt_enrichment_runtime as runtime

    current = parsed.enrich_prompt_with_active_release

    def frozen_writer(revision, templates, *args, **kwargs):
        return historical_result(current(revision, templates, *args, **kwargs), revision, templates)

    # Simulate the old writer, then restart on the current reader with persisted old histories.
    monkeypatch.setattr(parsed, "enrich_prompt_with_active_release", frozen_writer)
    monkeypatch.setattr(runtime, "enrich_prompt_with_active_release", frozen_writer)
    ctx = ready_session()
    _correct(ctx, "I prefer yellow.")
    _answer(ctx, "metal.color", decision="SKIP")
    _correct(ctx, "Do not add a halo.")
    with engine.connect() as db:
        before = {
            model.__tablename__: tuple(db.scalars(select(model.result_payload)))
            for model in (EnrichmentCycleRow, ClarificationAnswerRow, UserCorrectionRow)
        }
        revisions = {
            str(row.revision_id): validate_design_revision(row.snapshot)
            for row in db.execute(
                select(SpecificationRevisionRow.revision_id, SpecificationRevisionRow.snapshot)
            )
        }
    assert all(p["enrichment_version"] == "1.2.0" for p in before["enrichment_cycle"])
    correction = next(c for c in before["user_correction"] if c["prior_answer_results"])
    assert correction["next_enrichment_result"]["enrichment_version"] == "1.2.0"
    assert (
        correction["post_transition_evaluation"]["enrichment_result"]["enrichment_version"]
        == "1.2.0"
    )
    assert correction["prior_answer_results"]

    monkeypatch.setattr(parsed, "enrich_prompt_with_active_release", current)
    monkeypatch.setattr(runtime, "enrich_prompt_with_active_release", current)

    def forbidden(*args, **kwargs):
        pytest.fail("Historical restoration recompiled the old prompt")

    monkeypatch.setattr("jewelai_prompts.compiler.compile_prompt", forbidden)
    state = ctx.runtime.get_current_state(UUID(ctx.sid), UUID(ctx.org))
    assert state.final_output.internal_final_prompt.schema_version == "2.0.0"
    assert post(ctx).status_code == 201
    with engine.connect() as db:
        after = {
            model.__tablename__: tuple(db.scalars(select(model.result_payload)))
            for model in (EnrichmentCycleRow, ClarificationAnswerRow, UserCorrectionRow)
        }
    assert after == before

    # Validate original compiled sources wherever embedded in nested answers/corrections.
    # Use each source's actual historical revision, not today's current Product State.
    def historical_sources(value):
        if isinstance(value, dict):
            if value.get("enrichment_version") == "1.2.0":
                yield value
            for child in value.values():
                yield from historical_sources(child)
        elif isinstance(value, (list, tuple)):
            for child in value:
                yield from historical_sources(child)

    nested_count = 0
    for table in ("clarification_answer", "user_correction"):
        for nested in historical_sources(before[table]):
            historical = decode_prompt_enrichment_result(nested)
            revision = revisions[historical.design_revision_id]
            templates = ctx.service.artifacts.prompts
            validate_historical_compiled_source(historical.compiled_prompt, revision, templates)
            changed = deepcopy(nested)
            compiled = changed["compiled_prompt"]
            compiled["prompt_text"] = "Rehashed but not the historical canonical rendering."
            compiled["content_hash"] = hashlib.sha256(compiled["prompt_text"].encode()).hexdigest()
            changed["content_hash"] = ctx.service.repository._canonical_hash(
                {k: v for k, v in changed.items() if k != "content_hash"}
            )
            forged = decode_prompt_enrichment_result(changed)
            with pytest.raises(ValueError, match="historical compiled source"):
                validate_historical_compiled_source(forged.compiled_prompt, revision, templates)
            nested_count += 1
    assert nested_count > 0
    for payload in before["enrichment_cycle"]:
        assert decode_prompt_enrichment_result(payload).model_dump(mode="json") == payload
        forged = {**payload, "content_hash": "0" * 64}
        with pytest.raises(ValueError):
            decode_prompt_enrichment_result(forged)


def test_current_structured_writer_has_no_compiler_dependency(ready_session, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("The current canonical source used the historical compiler")

    monkeypatch.setattr("jewelai_prompts.compiler.compile_prompt", forbidden)
    ctx = ready_session()
    _correct(ctx, "Do not add a halo.")
    cycles = ctx.service.repository.list_enrichment_cycles(UUID(ctx.sid), UUID(ctx.org))
    assert all(isinstance(cycle.result, StructuredPromptEnrichmentResult) for cycle in cycles)
    assert all("compiled_prompt" not in cycle.result.model_dump() for cycle in cycles)
    assert post(ctx).status_code == 201
