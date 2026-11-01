"""Actual F HTTP output sources: strict versions, current frontier and availability."""

from copy import deepcopy
from uuid import UUID, uuid4

import pytest
from conftest import NOW
from jewelai_domain.models import MessageSource
from jewelai_domain.revisions import lock_field, revise_design
from jewelai_prompts.downstream_preparation import GenerationPreparationError, canonical_bytes
from jewelai_prompts.downstream_preparation_v2 import render_semantic_source_v2
from pydantic import ValidationError
from test_f04_http import READY_TEXT, answer, f04_session, initial, restart, state_get
from test_generation_preparations import counts
from test_prompt_enrichment_http import _message


@pytest.mark.parametrize(
    "mutation",
    [
        "gate_version",
        "overlay_hash",
        "frontier_hash",
        "missing_ifp_version",
        "source_version",
        "history_flag",
    ],
)
def test_f04_mixed_or_tampered_output_cannot_prepare(engine, tmp_path, mutation):
    with f04_session(engine, tmp_path) as ctx:
        state = initial(ctx, READY_TEXT)
        response, _ = answer(ctx, state)
        assert response.status_code == 200
        source, gate = ctx.runtime.build_preparation_source(ctx.repo, ctx.sid, ctx.org)
        assert render_semantic_source_v2(source, gate).schema_version == "2.0.0"
        s = source.model_dump(mode="json")
        g = gate.model_dump(mode="json")
        if mutation == "gate_version":
            g["schema_version"] = "1.0.0"
        elif mutation == "overlay_hash":
            g["availability_overlay_hash"] = "0" * 64
        elif mutation == "frontier_hash":
            g["effective_unresolved_frontier_hash"] = "0" * 64
        elif mutation == "missing_ifp_version":
            del s["internal_final_prompt"]["schema_version"]
        elif mutation == "source_version":
            s["schema_version"] = "2.1.0"
        else:
            s["internal_final_prompt"]["decision_lineage"][0]["blocks_progression"] = True
        with pytest.raises((ValueError, ValidationError, GenerationPreparationError)):
            render_semantic_source_v2(s, g)
        assert counts(engine) == (0, 0, 0, 0)


def test_f04_stale_frontier_rejected_and_preparation_bytes_retained(engine, tmp_path):
    with f04_session(engine, tmp_path) as ctx:
        state = initial(ctx, READY_TEXT)
        response, _ = answer(ctx, state)
        assert response.status_code == 200
        state = response.json()["state"]
        payload = {
            **state["preparation_expectations"],
            "expected_effective_frontier_hash": "0" * 64,
        }
        failed = ctx.client.post(
            f"/sessions/{ctx.sid}/generation-preparations",
            headers={**ctx.headers, "Idempotency-Key": str(uuid4())},
            json=payload,
        )
        assert failed.status_code == 409 and failed.json()["error"] == "stale_clarification_plan"
        assert counts(engine) == (0, 0, 0, 0)
        success = ctx.client.post(
            f"/sessions/{ctx.sid}/generation-preparations",
            headers={**ctx.headers, "Idempotency-Key": str(uuid4())},
            json=state["preparation_expectations"],
        )
        assert success.status_code == 201, success.json()
        from jewelai_persistence.models import GenerationPreparationRow
        from sqlalchemy import select

        with ctx.repo._session_factory() as db:
            row = db.scalar(
                select(GenerationPreparationRow).where(
                    GenerationPreparationRow.preparation_id
                    == UUID(success.json()["preparation_id"])
                )
            )
            before = bytes(row.artifact_bytes)
        with restart(ctx, engine):
            result = ctx.client.get(
                f"/sessions/{ctx.sid}/generation-preparations/{success.json()['preparation_id']}",
                headers=ctx.headers,
            )
            assert result.status_code == 200 and result.json() == success.json()
            with ctx.repo._session_factory() as db:
                row = db.scalar(
                    select(GenerationPreparationRow).where(
                        GenerationPreparationRow.preparation_id
                        == UUID(success.json()["preparation_id"])
                    )
                )
                assert bytes(row.artifact_bytes) == before
        assert counts(engine) == (1, 1, 0, 0)


@pytest.mark.parametrize("schema", ["1.0.0", "1.1.0"])
@pytest.mark.parametrize("requirement", ["required", "optional", "undetermined"])
def test_f04_canonical_unknown_and_sourced_na_survive_http_restart(
    engine, tmp_path, requirement, schema
):
    with f04_session(engine, tmp_path) as ctx:
        current = ctx.repo.get_current_revision(ctx.sid, ctx.org)
        message = _message(
            ctx.client, str(ctx.sid), str(ctx.org), "Explicit synthetic canonical prerequisites."
        )
        source = MessageSource(message_id=message["message_id"], recorded_at=NOW)
        design = deepcopy(current.design.model_dump(mode="json"))
        design["center_stone"]["dimensions"] = {
            "availability": "unknown",
            "requirement": requirement,
        }
        design["construction"]["clasp"] = {
            "availability": "not_applicable",
            "reason": "Synthetic explicit clasp exclusion.",
            "source": source.model_dump(mode="json"),
            "locked": False,
        }
        seeded = revise_design(
            current,
            design,
            expected_revision_id=current.revision_id,
            source=source,
            reason="Synthetic approved canonical state",
            created_at=NOW,
        )
        ctx.repo.append_revision_cas(ctx.sid, ctx.org, current.revision_id, seeded)
        locked = lock_field(
            seeded,
            "construction.clasp",
            expected_revision_id=seeded.revision_id,
            source=source,
            reason="Synthetic explicit N/A lock",
            created_at=NOW,
        )
        ctx.repo.append_revision_cas(ctx.sid, ctx.org, seeded.revision_id, locked)
        seeded = locked
        if schema == "1.1.0":
            from jewelai_domain.models_v1_1 import migrate_design_revision_v1_to_v1_1

            migrated = migrate_design_revision_v1_to_v1_1(
                seeded,
                revision_id=uuid4(),
                created_at=NOW,
                source=source,
                reason="Synthetic approved schema upgrade",
            )
            ctx.repo.upgrade_design_session_schema_v1_1(
                ctx.sid, ctx.org, seeded.revision_id, migrated
            )
            seeded = migrated
        state = initial(
            ctx, "A white gold ring with an oval diamond center stone in prong setting."
        )
        current = ctx.repo.get_current_revision(ctx.sid, ctx.org)
        assert current.design.center_stone.dimensions.requirement == requirement
        assert current.design.construction.clasp == seeded.design.construction.clasp
        bound = ctx.runtime._for_session(ctx.sid, ctx.org)
        restored = bound.get_current_state(ctx.sid, ctx.org)
        overlay = restored.final_output.internal_final_prompt.availability_overlay
        dimensions = next(
            e for e in overlay.entries if e.target.concrete_target == "center_stone.dimensions"
        )
        clasp = next(e for e in overlay.entries if e.target.concrete_target == "construction.clasp")
        assert (
            dimensions.availability == "UNKNOWN" and dimensions.unknown_requirement == requirement
        )
        assert clasp.availability == "NOT_APPLICABLE" and clasp.not_applicable.source == source
        assert clasp.locked and clasp.confirmed
        assert "Synthetic explicit clasp exclusion." in state["description"]["text"]
        assert not state["can_prepare"]
        snapshot = canonical_bytes(restored.final_output)
        with restart(ctx, engine):
            assert state_get(ctx) == state
            assert (
                canonical_bytes(ctx.runtime.get_current_state(ctx.sid, ctx.org).final_output)
                == snapshot
            )
