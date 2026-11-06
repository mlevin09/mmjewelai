"""Owner-approved non-destructive lifecycle through real scoped HTTP/SQLite."""

from uuid import UUID, uuid4

import pytest
from conftest import NOW, create_hierarchy
from jewelai_model_gateway import GenerationErrorCode
from jewelai_persistence.models import AssetRow, Base, DesignSessionRow, PromptCompletionRow
from sqlalchemy import select
from test_api import add_iteration_asset, complete_iteration_run, create_ready_prompt
from test_conversation import read
from test_f04_http import f04_session, restart
from test_f05_history import initial


def test_retirement_preserves_completed_native_history_and_restart(engine, tmp_path, monkeypatch):
    from functools import partial

    import test_prompt_enrichment_composition as composition
    from conftest import ROOT
    from jewelai_prompts.completion import CompletionRegistry

    registry = CompletionRegistry.model_validate_json(
        (ROOT / "data/completion/preprod-no-defaults-1.0.0.json").read_bytes()
    )
    monkeypatch.setattr(
        composition, "create_app", partial(composition.create_app, completion_registry=registry)
    )
    with f04_session(engine, tmp_path) as ctx:
        initial(ctx, "F", "A white gold ring with an oval diamond center stone in prong setting.")
        snapshot = read(ctx)
        message = ctx.client.post(
            f"/sessions/{ctx.sid}/messages", headers=ctx.headers, json={"content": "NO"}
        ).json()
        done = ctx.client.post(
            f"/v1/sessions/{ctx.sid}/prompt-enrichment/completions",
            headers=ctx.headers,
            json={
                "schema_version": "1.0.0",
                "request_id": str(uuid4()),
                "message_id": message["message_id"],
                "expected_frame": snapshot["state"]["current_frame"],
                "anything_else": "NO",
            },
        )
        assert done.status_code == 200, done.json()
        final = done.json()["final_prompt"]
        with engine.connect() as db:
            source = db.execute(select(PromptCompletionRow.payload)).scalar_one()
            history = {
                name: db.execute(select(table).where(table.c.session_id == ctx.sid)).all()
                for name, table in Base.metadata.tables.items()
                if name != "design_session" and "session_id" in table.c
            }
        sibling = ctx.client.post(
            f"/projects/{ctx.legacy['project_id']}/sessions",
            headers=ctx.headers,
            json={"role_id": "retail_client", "locale": "en"},
        ).json()
        path = f"/sessions/{ctx.sid}"
        assert ctx.client.delete(path, headers=ctx.headers).status_code == 204
        with engine.connect() as db:
            tombstone = db.execute(
                select(DesignSessionRow.deleted_at, DesignSessionRow.deleted_by_principal_id).where(
                    DesignSessionRow.session_id == ctx.sid
                )
            ).one()
        assert all(tombstone)
        assert (
            ctx.client.delete(
                path.upper().replace("/SESSIONS/", "/sessions/"), headers=ctx.headers
            ).status_code
            == 204
        )
        for tail in [
            "",
            "/revisions",
            "/assets",
            "/generation-runs",
            "/visualization-iterations",
        ]:
            assert ctx.client.get(path + tail, headers=ctx.headers).status_code == 404
        assert (
            ctx.client.get(
                f"/v1/sessions/{ctx.sid}/prompt-enrichment/conversation", headers=ctx.headers
            ).status_code
            == 404
        )
        assert (
            ctx.client.post(
                path + "/messages", headers=ctx.headers, json={"content": "Must not append"}
            ).status_code
            == 404
        )
        listed = ctx.client.get(
            f"/projects/{ctx.legacy['project_id']}/sessions", headers=ctx.headers
        ).json()["sessions"]
        assert str(ctx.sid) not in [s["session_id"] for s in listed]
        assert sibling["session_id"] in [s["session_id"] for s in listed]
        with restart(ctx, engine):
            assert ctx.client.get(path, headers=ctx.headers).status_code == 404
            assert (
                ctx.client.get(
                    f"/sessions/{sibling['session_id']}", headers=ctx.headers
                ).status_code
                == 200
            )
        with engine.connect() as db:
            assert db.execute(select(PromptCompletionRow.payload)).scalar_one() == source
            assert {
                name: db.execute(
                    select(Base.metadata.tables[name]).where(
                        Base.metadata.tables[name].c.session_id == ctx.sid
                    )
                ).all()
                for name in history
            } == history
            assert (
                db.execute(
                    select(
                        DesignSessionRow.deleted_at, DesignSessionRow.deleted_by_principal_id
                    ).where(DesignSessionRow.session_id == ctx.sid)
                ).one()
                == tombstone
            )
        assert final["canonical_revision"] == snapshot["revision"]


@pytest.mark.parametrize("role,expected", [("owner", 204), ("admin", 204), ("member", 403)])
def test_retirement_requires_owner_or_admin_in_exact_organization(client, role, expected):
    oid, _, session = create_hierarchy(client)
    headers = {"Authorization": "Bearer test-retirer", "X-Organization-ID": oid}
    actor = client.get("/me", headers=headers).json()["principal_id"]
    assert (
        client.post(
            f"/organizations/{oid}/memberships", json={"principal_id": actor, "role": role}
        ).status_code
        == 201
    )
    assert (
        client.delete(f"/sessions/{session.json()['session_id']}", headers=headers).status_code
        == expected
    )
    if expected == 403:
        assert (
            client.get(f"/sessions/{session.json()['session_id']}", headers=headers).status_code
            == 200
        )


def test_retirement_authentication_cross_tenant_and_unknown_session(client):
    oid, _, session = create_hierarchy(client)
    other, _, other_session = create_hierarchy(client)
    path = f"/sessions/{session.json()['session_id']}"
    assert (
        client.delete(path, headers={"Authorization": "", "X-Organization-ID": oid}).status_code
        == 401
    )
    assert client.delete(path, headers={"X-Organization-ID": other}).status_code == 404
    assert (
        client.delete(
            "/sessions/00000000-0000-0000-0000-000000000000", headers={"X-Organization-ID": oid}
        ).status_code
        == 404
    )
    assert client.get(path, headers={"X-Organization-ID": oid}).status_code == 200
    assert (
        client.get(
            f"/sessions/{other_session.json()['session_id']}", headers={"X-Organization-ID": other}
        ).status_code
        == 200
    )


@pytest.mark.parametrize("running", [False, True])
def test_retirement_blocks_active_generation_and_preserves_outbox(client, app, running):
    oid, _, session, _, prompt = create_ready_prompt(client)
    headers = {"X-Organization-ID": oid}
    path = f"/sessions/{session['session_id']}"
    run = client.post(
        path + "/generation-runs",
        headers=headers,
        json={"prompt_revision_id": prompt["prompt_revision_id"], "profile_id": "test_default"},
    ).json()
    repo = app.state.service.repository
    rid, sid, org = UUID(run["generation_run_id"]), UUID(session["session_id"]), UUID(oid)
    if running:
        repo.claim_generation_run(sid, rid, org, NOW)
    assert client.delete(path, headers=headers).status_code == 409
    assert client.get(path, headers=headers).status_code == 200
    if not running:
        repo.claim_generation_run(sid, rid, org, NOW)
    repo.fail_generation_run(
        sid, rid, org, GenerationErrorCode.PROVIDER_REJECTED, "Synthetic failure", NOW
    )
    before = repo.get_generation_dispatch(rid)
    assert client.delete(path, headers=headers).status_code == 204
    after = repo.get_generation_dispatch(rid)
    assert (after.generation_run_id, after.created_at, after.published_at) == (
        before.generation_run_id,
        before.created_at,
        before.published_at,
    )
    assert client.post(path + f"/generation-runs/{rid}/retry", headers=headers).status_code == 404


def test_retirement_waits_for_successful_run_asset_finalization(client, app, engine):
    oid, project, session, _, prompt = create_ready_prompt(client)
    headers = {"X-Organization-ID": oid}
    path = f"/sessions/{session['session_id']}"
    run = client.post(
        path + "/generation-runs",
        headers=headers,
        json={"prompt_revision_id": prompt["prompt_revision_id"], "profile_id": "test_default"},
    ).json()
    repo = app.state.service.repository
    complete_iteration_run(repo, run, oid, succeed=True)
    assert client.delete(path, headers=headers).status_code == 409
    asset_id = add_iteration_asset(repo, run, oid, project, session["session_id"])
    with engine.connect() as db:
        before = db.execute(select(AssetRow.__table__).where(AssetRow.asset_id == asset_id)).one()
    assert client.delete(path, headers=headers).status_code == 204
    assert (
        client.post(path + f"/assets/{asset_id}/access", headers=headers, json={}).status_code
        == 404
    )
    with engine.connect() as db:
        assert (
            db.execute(select(AssetRow.__table__).where(AssetRow.asset_id == asset_id)).one()
            == before
        )
