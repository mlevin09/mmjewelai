"""Rehashed retained input is not authority over its actual historical source."""

import hashlib
from uuid import UUID, uuid4

import pytest
from jewelai_persistence.models import GenerationCommandRow, GenerationPreparationRow
from jewelai_prompts import GenerationPreparation
from jewelai_prompts.downstream_preparation import build_generation_preparation, canonical_bytes
from sqlalchemy import select
from test_effective_readiness import _correct
from test_effective_readiness import ready_session as ready_session
from test_generation_preparations import expected, post


def _rehash(payload):
    payload["content_hash"] = hashlib.sha256(
        canonical_bytes({k: v for k, v in payload.items() if k != "content_hash"})
    ).hexdigest()


@pytest.mark.parametrize(
    "field,value",
    [
        ("package_id", "jewelai.independent.forged-release"),
        ("artifact_version", "99.0.0"),
        ("runtime_sha256", "b" * 64),
        ("validation_report_sha256", "c" * 64),
    ],
)
def test_coherently_forged_retained_knowledge_rejected_by_get_and_replay(
    ready_session, engine, field, value
):
    ctx = ready_session()
    request, original_key = expected(ctx), uuid4()
    created = post(ctx, request, original_key)
    assert created.status_code == 201
    original_id, forged_id, key = UUID(created.json()["preparation_id"]), uuid4(), uuid4()
    with engine.connect() as db:
        original = dict(db.execute(select(GenerationPreparationRow)).mappings().one())
        command = dict(db.execute(select(GenerationCommandRow)).mappings().one())
    retained = GenerationPreparation(original["artifact_bytes"]).payload
    source = retained.source_handoff.model_dump(mode="json")
    gate = retained.gate_evidence.model_dump(mode="json")
    source["knowledge_release"][field] = value
    prompt = source["internal_final_prompt"]
    prompt["knowledge_release"][field] = value
    for item in prompt["decision_lineage"]:
        item["knowledge_" + ("package_id" if field == "package_id" else field)] = value
    _rehash(prompt)
    source["internal_final_prompt_content_hash"] = prompt["content_hash"]
    _rehash(source)
    gate["knowledge_release"][field] = value
    gate["source_handoff_hash"] = source["content_hash"]
    forged = build_generation_preparation(
        source, gate, preparation_id=forged_id, created_at=retained.created_at
    )
    p = forged.payload
    # INSERT a new synthetic malformed record; never UPDATE/delete the original immutable row.
    altered = {
        **original,
        "preparation_id": forged_id,
        "artifact_bytes": forged.canonical,
        "artifact_payload": forged.model_dump(),
        "source_bytes": canonical_bytes(p.source_handoff),
        "rendering_hash": p.execution.rendering_hash,
        **{
            f: getattr(p, f)
            for f in (
                "source_handoff_hash",
                "source_bytes_sha256",
                "gate_evidence_hash",
                "artifact_hash",
            )
        },
    }
    frozen = {
        **created.json(),
        "preparation_id": str(forged_id),
        "source_handoff_hash": p.source_handoff_hash,
        "artifact_hash": p.artifact_hash,
        "rendering_hash": p.execution.rendering_hash,
    }
    response_bytes = canonical_bytes(frozen)
    with engine.begin() as db:
        db.execute(GenerationPreparationRow.__table__.insert().values(**altered))
        db.execute(
            GenerationCommandRow.__table__.insert().values(
                **{
                    **command,
                    "idempotency_key": key,
                    "preparation_id": forged_id,
                    "response_bytes": response_bytes,
                    "response_hash": hashlib.sha256(response_bytes).hexdigest(),
                }
            )
        )
    for response in (
        ctx.client.get(
            f"/sessions/{ctx.sid}/generation-preparations/{forged_id}", headers=ctx.headers
        ),
        post(ctx, request, key),
    ):
        assert response.status_code == 500 and response.json()["error"] == "invalid_durable_history"
    _correct(ctx, "Do not add a halo.")
    assert (
        ctx.client.get(
            f"/sessions/{ctx.sid}/generation-preparations/{original_id}", headers=ctx.headers
        ).json()
        == created.json()
    )
    assert post(ctx, request, original_key).json() == created.json()
    with engine.connect() as db:
        after = dict(
            db.execute(
                select(GenerationPreparationRow).where(
                    GenerationPreparationRow.preparation_id == original_id
                )
            )
            .mappings()
            .one()
        )
    assert after == original
