"""Admitted Parse1.2 uses the existing proposal/Matrix without canonical authority."""

from datetime import UTC
from uuid import UUID, uuid4

import pytest
from jewelai_domain.models import MessageSource
from test_f04_http import f04_session
from test_f05_admission import admit, rows
from test_f05_history import initial
from test_prompt_enrichment_http import _message

from jewelai_api.continuation_evaluation import ParsedEvaluationV3, evaluate_continuation_message
from jewelai_api.f04_planning import input_context
from jewelai_api.parsed_enrichment import ParsedCandidateEnrichmentResult


@pytest.mark.parametrize("base", ["L", "F"])
@pytest.mark.parametrize(
    "locale,text,positive",
    [
        ("en", "Emerald cut center stone.", True),
        ("ru", "Изумрудная огранка центрального камня.", True),
        ("ru", "Emerald cut центрального камня.", True),
        ("en", "Round center stone.", False),
        ("en", "Do not use emerald cut center stone.", False),
        ("en", "Maybe emerald cut center stone.", False),
    ],
)
def test_new_parse_and_native_matrix_are_sourced_evidence_not_a_revision(
    engine, tmp_path, base, locale, text, positive
):
    with f04_session(engine, tmp_path, locale=locale) as ctx:
        initial(ctx, base)
        ctx.runtime.continuation_enabled = True
        admission, _ = admit(ctx)
        assert admission.status_code == 201, admission.json()
        control = _message(ctx.client, str(ctx.sid), str(ctx.org), text)
        message = ctx.repo.get_message(ctx.sid, UUID(control["message_id"]), ctx.org)
        source = MessageSource(
            message_id=str(message.message_id), recorded_at=message.created_at.replace(tzinfo=UTC)
        )
        before = rows(ctx)
        service = ctx.runtime._for_session(ctx.sid, ctx.org)
        cycle = before[1][-1]
        context = cycle.result.context
        verified = ctx.repo.restore_pinned_knowledge_runtime(
            ctx.sid,
            ctx.org,
            service.artifact_store,
            active_release=service.active_release,
            validation_report=service.validation_report,
        )
        native = (
            input_context(
                context.scope,
                before[0],
                uuid4(),
                cycle.cycle_number + 1,
                service.artifacts,
                cycle.release_pin,
            )
            if base == "F"
            else None
        )
        result = evaluate_continuation_message(
            service,
            before[0],
            message,
            source,
            context=context,
            verified_release=verified,
            role_id=service.repository.get_design_session(ctx.sid, ctx.org).role_id,
            locale=locale,
            native_context=native,
        )
        assert result.evaluation_version == "3.0.0"
        assert result.parse_result.parse_version == "1.2.0"
        assert result.parse_result.original_text == text
        assert result.parser_proposal.source == source
        updates = result.parser_proposal.accepted_updates
        matched = any(
            u.concrete_target == "center_stone.shape" and u.canonical_value == "emerald_cut"
            for u in updates
        )
        assert matched is positive
        assert not any("dimensions" in u.concrete_target for u in updates)
        assert rows(ctx) == before
        assert ParsedEvaluationV3.model_validate_json(result.model_dump_json()) == result
        # Native evaluation readers accept Parse1.2, but never a V3 envelope.
        with pytest.raises(ValueError):
            ParsedCandidateEnrichmentResult.model_validate(result.model_dump(mode="json"))
        # A proposal may not be attributed to another Message or source time.
        with pytest.raises(ValueError):
            evaluate_continuation_message(
                service,
                before[0],
                message,
                source.model_copy(update={"message_id": str(uuid4())}),
                context=context,
                verified_release=verified,
                role_id=service.repository.get_design_session(ctx.sid, ctx.org).role_id,
                locale=locale,
                native_context=native,
            )
        assert ctx.provider.calls == []
