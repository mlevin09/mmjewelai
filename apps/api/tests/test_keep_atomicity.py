"""Bounded real HTTP and fresh-process proof of native KEEP/write atomicity."""

import json
import os
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path
from uuid import UUID, uuid4

import pytest
import test_style_input as style_tests
from conftest import NOW, ROOT
from jewelai_persistence import (
    Base,
    PersistenceRepository,
    create_database_engine,
    create_session_factory,
)
from sqlalchemy import event, select
from test_f04_http import f04_session
from test_f04_http import initial as initial_f
from test_f05_history import READY
from test_prompt_enrichment_http import _client, _message

from jewelai_api import prompt_enrichment_runtime, prompt_enrichment_runtime_v2
from jewelai_api.prompt_enrichment_runtime import PromptEnrichmentRuntimeService

ready_session = style_tests.ready_session
style_session = style_tests.style_session

TEXT = (
    "Keep the center stone exactly as specified. Do not change its dimensions. "
    "Use a refined, minimalist appearance."
)


@contextmanager
def _context(profile, route, engine, tmp_path, style_session):
    if profile == "L":
        yield style_session(route)
    else:
        with f04_session(engine, tmp_path, binding=True) as ctx:
            if route == "corrections":
                initial_f(ctx, READY.replace(" Keep the center stone unchanged.", ""))
            yield ctx


def _snapshot(engine, sid):
    result = {}
    with engine.connect() as db:
        for table in Base.metadata.sorted_tables:
            if "session_id" in table.c:
                rows = db.execute(select(table).where(table.c.session_id == UUID(str(sid))))
                result[table.name] = sorted(
                    (json.loads(json.dumps(dict(r), default=str)) for r in rows.mappings()),
                    key=lambda v: json.dumps(v, sort_keys=True),
                )
    return result


@contextmanager
def _staged_inserts(engine):
    tables = []

    def record(conn, cursor, statement, parameters, context, executemany):
        command = getattr(getattr(context, "compiled", None), "statement", None)
        if getattr(command, "is_insert", False):
            tables.append(command.table.name)

    event.listen(engine, "after_cursor_execute", record)
    try:
        yield tables
    finally:
        event.remove(engine, "after_cursor_execute", record)


def _request(ctx, profile, route, text):
    sid, org = UUID(str(ctx.sid)), UUID(str(ctx.org))
    repo = ctx.runtime.repository
    message = _message(ctx.client, str(sid), str(org), text)
    current = repo.get_current_revision(sid, org)
    payload = dict(message_id=message["message_id"], expected_revision_id=str(current.revision_id))
    if profile == "F":
        payload["schema_version"] = "2.0.0"
        if route == "corrections":
            state = ctx.runtime.get_current_state(sid, org)
            payload.update(
                expected_enrichment_cycle_id=str(state.enrichment_cycle_id),
                expected_enrichment_result_hash=repo.list_enrichment_cycles(sid, org)[
                    -1
                ].result.content_hash,
                expected_clarification_plan_hash=state.clarification_plan.content_hash,
            )
    return payload, current, message


def _post(ctx, route, payload):
    return ctx.client.post(
        f"/v1/sessions/{ctx.sid}/prompt-enrichment/{route}",
        headers=ctx.headers,
        json=payload,
    )


def _record(name, evidence):
    folder = os.getenv("F05_KEEP_EVIDENCE_DIR")
    if folder:
        path = Path(folder)
        path.mkdir(parents=True, exist_ok=True)
        (path / (name + ".json")).write_text(json.dumps(evidence, ensure_ascii=False, indent=2))


def _restart(ctx, engine, tmp_path, expected):
    """The child opens the SQLite file itself; no inherited engine/session or app."""
    assert engine.dialect.name == "sqlite" and engine.url.database not in (None, ":memory:")
    runtime = ctx.runtime
    config = dict(
        database_url=str(engine.url),
        session_id=str(ctx.sid),
        organization_id=str(ctx.org),
        store_root=str(runtime.artifact_store.root),
        package_id=runtime.knowledge_package_id,
        artifact_version=runtime.knowledge_artifact_version,
        active=runtime.active_release.model_dump(mode="json"),
        report=runtime.validation_report.model_dump(mode="json"),
        artifact_versions=vars(runtime.artifacts.versions),
    )
    source, destination = tmp_path / f"{uuid4()}.json", tmp_path / f"{uuid4()}.json"
    source.write_text(json.dumps(config))
    source.chmod(0o600)
    before = _snapshot(engine, ctx.sid)
    result = subprocess.run(
        [sys.executable, str(Path(__file__).resolve()), str(source), str(destination)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=45,
    )
    assert result.returncode == 0, result.stderr
    actual = json.loads(destination.read_text())
    if expected is not None:
        assert actual["state"] == expected.model_dump(mode="json")
        assert actual["http_status"] == 200
    else:
        assert actual["state"] is None and actual["http_status"] != 200
    assert actual["provider_calls"] == 0 and _snapshot(engine, ctx.sid) == before
    return actual


@pytest.mark.parametrize("profile", ["L", "F"])
@pytest.mark.parametrize("route", ["initial", "corrections"])
def test_keep_has_one_full_source_and_consistent_output_after_process_restart(
    style_session, engine, tmp_path, profile, route
):
    with _context(profile, route, engine, tmp_path, style_session) as ctx:
        payload, previous, message = _request(ctx, profile, route, TEXT)
        before = _snapshot(engine, ctx.sid)
        response = _post(ctx, route, payload)
        assert response.status_code == (201 if route == "initial" else 200), response.json()
        sid, org = UUID(str(ctx.sid)), UUID(str(ctx.org))
        state = ctx.runtime.get_current_state(sid, org)
        current = ctx.runtime.repository.get_current_revision(sid, org)
        assert current.design.center_stone == previous.design.center_stone
        assert current.design.style.value == ("minimalist",)
        assert not current.design.style.locked and not current.design.style.confirmed
        assert current.design.style.source.message_id == message["message_id"]
        keeps = [
            c
            for c in state.clarification_plan.constraint_evidence
            if c.status == "active" and c.semantic_subject == "component.center_stone"
        ]
        assert len(keeps) == 1 and keeps[0].kind == "preservation"
        assert keeps[0].original_wording == "Keep the center stone exactly as specified"
        assert keeps[0].source.message_id == message["message_id"]
        assert (
            TEXT[keeps[0].source_span_start : keeps[0].source_span_end] == keeps[0].original_wording
        )
        prompt = state.final_output.internal_final_prompt
        assert len([c for c in prompt.constraints if c.target == "component.center_stone"]) == 1
        assert "minimalist" in state.final_output.description.text.lower()
        restarted = _restart(ctx, engine, tmp_path, state)
        _record(
            f"success-{profile}-{route}",
            dict(
                input=TEXT,
                request=payload,
                status=response.status_code,
                response=response.json(),
                before=before,
                after=_snapshot(engine, ctx.sid),
                canonical=current.model_dump(mode="json"),
                final_output=state.final_output.model_dump(mode="json"),
                restart=restarted,
            ),
        )
        assert ctx.provider.calls == []


@pytest.mark.parametrize("profile", ["L", "F"])
@pytest.mark.parametrize("route", ["initial", "corrections"])
def test_rejected_final_snapshot_rolls_back_all_staged_rows_and_pin(
    style_session, engine, tmp_path, profile, route
):
    with _context(profile, route, engine, tmp_path, style_session) as ctx:
        text = "Include a halo. Do not add a halo. Make the design minimalist."
        payload, _, _ = _request(ctx, profile, route, text)
        before = _snapshot(engine, ctx.sid)
        previous = (
            ctx.runtime.get_current_state(UUID(str(ctx.sid)), UUID(str(ctx.org)))
            if route == "corrections"
            else None
        )
        with _staged_inserts(engine) as staged:
            response = _post(ctx, route, payload)
        assert response.status_code == (422 if profile == "L" else 500), response.json()
        assert "enrichment_cycle" in staged and "clarification_plan" in staged
        assert _snapshot(engine, ctx.sid) == before
        restarted = _restart(ctx, engine, tmp_path, previous)
        _record(
            f"rollback-{profile}-{route}",
            dict(
                input=text,
                request=payload,
                status=response.status_code,
                response=response.json(),
                before=before,
                after=_snapshot(engine, ctx.sid),
                restart=restarted,
                staged_insert_tables=staged,
            ),
        )


@pytest.mark.parametrize("profile", ["L", "F"])
def test_typed_result_construction_failure_rolls_back_before_commit(
    style_session, engine, tmp_path, profile, monkeypatch
):
    with _context(profile, "initial", engine, tmp_path, style_session) as ctx:
        payload, _, _ = _request(ctx, profile, "initial", TEXT)
        before = _snapshot(engine, ctx.sid)
        module = prompt_enrichment_runtime if profile == "L" else prompt_enrichment_runtime_v2
        name = (
            "InitialEnrichmentRuntimeResult"
            if profile == "L"
            else "InitialEnrichmentRuntimeResultV2"
        )
        constructor = getattr(module, name)

        def reject_result(**fields):
            return constructor(**{**fields, "parser_proposal": None})

        with monkeypatch.context() as patch:
            patch.setattr(module, name, reject_result)
            with _staged_inserts(engine) as staged:
                response = _post(ctx, "initial", payload)
        assert response.status_code == (422 if profile == "L" else 500)
        assert "enrichment_cycle" in staged and "clarification_plan" in staged
        assert _snapshot(engine, ctx.sid) == before
        # The exact same Message and expected revision can now succeed: no phantom initial cycle.
        retry = _post(ctx, "initial", payload)
        assert retry.status_code == 201, retry.json()
        _record(
            f"typed-result-{profile}",
            dict(
                request=payload,
                rejected_status=response.status_code,
                staged_insert_tables=staged,
                before=before,
                unchanged_after_rejection=True,
                retry_status=retry.status_code,
            ),
        )


def test_independent_keep_sources_survive_unrelated_accepted_correction(style_session):
    ctx = style_session("corrections")
    text = "Keep the center stone exactly as specified. Preserve the band."
    payload, _, message = _request(ctx, "L", "corrections", text)
    response = _post(ctx, "corrections", payload)
    assert response.status_code == 200, response.json()
    sid, org = UUID(str(ctx.sid)), UUID(str(ctx.org))
    state = ctx.runtime.get_current_state(sid, org)
    keeps = tuple(c for c in state.clarification_plan.constraint_evidence if c.status == "active")
    assert {c.semantic_subject for c in keeps} == {"component.center_stone", "component.band"}
    assert all(c.source.message_id == message["message_id"] for c in keeps)
    payload, _, _ = _request(ctx, "L", "corrections", "Make the design minimalist.")
    response = _post(ctx, "corrections", payload)
    assert response.status_code == 200, response.json()
    state = ctx.runtime.get_current_state(sid, org)
    assert (
        tuple(c for c in state.clarification_plan.constraint_evidence if c.status == "active")
        == keeps
    )
    assert {c.target for c in state.final_output.internal_final_prompt.constraints} >= {
        "component.center_stone",
        "component.band",
    }


def _restart_probe(config_path, output_path):
    from datetime import datetime

    from jewelai_domain.knowledge_activation_v1_1 import (
        ActiveKnowledgeRuntimeV1_1,
        ProductionValidationReportV1_1,
    )
    from jewelai_domain.knowledge_storage_v1_1 import KnowledgeArtifactStoreV1_1

    from jewelai_api.artifacts import load_runtime_artifacts
    from jewelai_api.prompt_enrichment_runtime import PromptEnrichmentRuntimeError
    from jewelai_api.settings import ArtifactVersions

    config = json.loads(Path(config_path).read_text())
    engine = create_database_engine(config["database_url"])
    runtime = PromptEnrichmentRuntimeService(
        PersistenceRepository(create_session_factory(engine)),
        load_runtime_artifacts(ROOT, ArtifactVersions(**config["artifact_versions"])),
        KnowledgeArtifactStoreV1_1(config["store_root"]),
        knowledge_package_id=config["package_id"],
        knowledge_artifact_version=config["artifact_version"],
        active_release=ActiveKnowledgeRuntimeV1_1.model_validate(config["active"]),
        validation_report=ProductionValidationReportV1_1.model_validate(config["report"]),
        clock=lambda: datetime.fromisoformat(NOW.isoformat()),
        uuid_factory=uuid4,
    )
    client, provider = _client(engine, runtime)
    with client:
        response = client.get(
            f"/v1/sessions/{config['session_id']}/prompt-enrichment/state",
            headers={"X-Organization-ID": config["organization_id"]},
        )
        try:
            state = runtime.get_current_state(
                UUID(config["session_id"]), UUID(config["organization_id"])
            ).model_dump(mode="json")
        except PromptEnrichmentRuntimeError:
            state = None
        Path(output_path).write_text(
            json.dumps(
                dict(
                    state=state,
                    http_status=response.status_code,
                    response=response.json(),
                    provider_calls=len(provider.calls),
                )
            )
        )
    engine.dispose()


if __name__ == "__main__":
    _restart_probe(sys.argv[1], sys.argv[2])


@pytest.mark.parametrize("profile", ["L", "F"])
def test_compatible_same_subject_keep_http_lifecycle(style_session, engine, tmp_path, profile):
    with _context(profile, "corrections", engine, tmp_path, style_session) as ctx:
        text = "Keep the center stone. Preserve the original center stone."
        payload, previous, message = _request(ctx, profile, "corrections", text)
        before = _snapshot(engine, ctx.sid)
        response = _post(ctx, "corrections", payload)
        _record(
            f"same-subject-{profile}",
            dict(
                input=text,
                status=response.status_code,
                response=response.json(),
                before=before,
                after=_snapshot(engine, ctx.sid),
            ),
        )
        assert response.status_code == 200, response.json()
        sid, org = UUID(str(ctx.sid)), UUID(str(ctx.org))
        current = ctx.runtime.repository.get_current_revision(sid, org)
        assert current == previous
        state = ctx.runtime.get_current_state(sid, org)
        evidence = [
            c
            for c in state.clarification_plan.constraint_evidence
            if c.semantic_subject == "component.center_stone"
        ]
        assert len(evidence) == 2
        assert {(c.source_span_start, c.source_span_end, c.original_wording) for c in evidence} == {
            (0, 21, "Keep the center stone"),
            (23, 57, "Preserve the original center stone"),
        }
        assert len({c.source_candidate_id for c in evidence}) == 2
        assert all(c.source.message_id == message["message_id"] for c in evidence)
        active = next(c for c in evidence if c.status == "active")
        old = next(c for c in evidence if c.status == "superseded")
        assert old.superseded_by_evidence_id == active.evidence_id
        assert (
            len(
                [
                    c
                    for c in state.final_output.internal_final_prompt.constraints
                    if c.target == "component.center_stone"
                ]
            )
            == 1
        )
        assert "Preserve:" in state.final_output.description.text
        preview = ctx.client.get(
            f"/v1/sessions/{ctx.sid}/prompt-enrichment/state?workflow_version=3.0.0",
            headers=ctx.headers,
        )
        assert preview.status_code == 200, preview.json()
        roots = preview.json()["protection_projection"]["roots"]
        assert len(roots) == 1 and len(roots[0]["scope_targets"]) in (8, 14)
        after = _snapshot(engine, ctx.sid)
        replay = _post(ctx, "corrections", payload)
        assert replay.status_code in (200, 409)
        assert _snapshot(engine, ctx.sid) == after
        payload, _, _ = _request(ctx, profile, "corrections", "Make the design minimalist.")
        assert _post(ctx, "corrections", payload).status_code == 200
        state = ctx.runtime.get_current_state(sid, org)
        assert [
            c
            for c in state.clarification_plan.constraint_evidence
            if c.semantic_subject == "component.center_stone"
        ] == evidence
        _restart(ctx, engine, tmp_path, state)
        payload, _, _ = _request(ctx, profile, "corrections", "Include a halo. Do not add a halo.")
        before_reject = _snapshot(engine, ctx.sid)
        rejected = _post(ctx, "corrections", payload)
        assert rejected.status_code == (422 if profile == "L" else 500)
        assert _snapshot(engine, ctx.sid) == before_reject
        restarted = _restart(ctx, engine, tmp_path, state)
        _record(
            f"same-subject-{profile}",
            dict(
                input=text,
                status=response.status_code,
                evidence=[c.model_dump(mode="json") for c in evidence],
                canonical_unchanged=current == previous,
                response=response.json(),
                replay_status=replay.status_code,
                rejected_status=rejected.status_code,
                rollback_unchanged=True,
                restart=restarted,
            ),
        )


@pytest.mark.parametrize("profile", ["L", "F"])
def test_distinct_same_subject_scopes_do_not_silently_merge_http(
    style_session, engine, tmp_path, profile
):
    with _context(profile, "corrections", engine, tmp_path, style_session) as ctx:
        text = "Keep the center stone shape unchanged. Preserve the original center stone."
        payload, _, _ = _request(ctx, profile, "corrections", text)
        before = _snapshot(engine, ctx.sid)
        response = _post(ctx, "corrections", payload)
        assert response.status_code == (422 if profile == "L" else 500), response.json()
        assert _snapshot(engine, ctx.sid) == before
        _record(
            f"distinct-scopes-{profile}",
            dict(
                input=text,
                status=response.status_code,
                error=response.json()["error"],
                rows_unchanged=True,
            ),
        )
