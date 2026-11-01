"""F05 read paths on the existing independently identified disposable PG service.

This proves the implemented preview/projection subset, not the unfinished F05
writer transaction/rollback/concurrency requirements.
"""

import pytest
from test_f05_compatibility import (
    test_required_unknown_is_discharged_only_by_actual_same_target_correction as _unknown,
)
from test_f05_preview import (
    test_negotiated_output_roundtrip_restart_no_writes_and_no_preparation as _read_only,
)
from test_f05_preview import (
    test_orphan_message_does_not_stale_but_correction_does as _stale,
)
from test_generation_preparations_postgres import engine as engine

pytestmark = pytest.mark.postgres


@pytest.mark.parametrize("base", ["L", "F"])
@pytest.mark.parametrize("locale", ["en", "ru"])
def test_f05_read_projection_postgres(engine, tmp_path, base, locale):
    _read_only(engine, tmp_path, base, locale)


def test_f05_unknown_causal_projection_postgres(engine, tmp_path):
    _unknown(engine, tmp_path, "EN")


def test_f05_read_frame_cas_postgres(engine, tmp_path):
    _stale(engine, tmp_path)


@pytest.mark.parametrize("base", ["L", "F"])
def test_f05_admission_roundtrip_postgres(engine, tmp_path, base):
    from test_f05_admission import test_admission_persists_cycle_plan3_and_replays_on_restart

    test_admission_persists_cycle_plan3_and_replays_on_restart(engine, tmp_path, base)


@pytest.mark.parametrize("base", ["L", "F"])
def test_f05_admission_atomic_rollback_postgres(engine, tmp_path, base):
    from test_f05_admission import test_admission_output_and_plan_failure_roll_back_entire_unit

    test_admission_output_and_plan_failure_roll_back_entire_unit(engine, tmp_path, base)


@pytest.mark.parametrize("base", ["L", "F"])
def test_f05_admitted_reads_postgres(engine, tmp_path, base):
    from test_f05_admission import (
        test_admitted_current_outputs_are_read_only_and_old_reads_are_explicitly_refused,
    )

    test_admitted_current_outputs_are_read_only_and_old_reads_are_explicitly_refused(
        engine, tmp_path, base
    )


@pytest.mark.parametrize("base", ["L", "F"])
def test_f05_competing_admissions_postgres(engine, tmp_path, base):
    from concurrent.futures import ThreadPoolExecutor
    from uuid import uuid4

    from test_f04_http import f04_session
    from test_f05_admission import rows
    from test_f05_history import initial
    from test_f05_preview import state
    from test_prompt_enrichment_http import _message

    with f04_session(engine, tmp_path) as ctx:
        initial(ctx, base)
        ctx.runtime.continuation_enabled = True
        expected = state(ctx)["current_frame"]
        before = rows(ctx)
        messages = [
            _message(ctx.client, str(ctx.sid), str(ctx.org), "Synthetic explicit admission.")
            for _ in range(2)
        ]
        requests = [
            dict(
                schema_version="1.0.0",
                request_id=str(uuid4()),
                message_id=m["message_id"],
                expected_head=expected,
            )
            for m in messages
        ]

        def invoke(request):
            return ctx.client.post(
                f"/v1/sessions/{ctx.sid}/prompt-enrichment/continuation-admissions",
                headers=ctx.headers,
                json=request,
            )

        with ThreadPoolExecutor(max_workers=2) as pool:
            responses = tuple(pool.map(invoke, requests))
        assert sorted(r.status_code for r in responses) == [201, 409], [r.json() for r in responses]
        after = rows(ctx)
        assert after[0] == before[0]
        assert len(after[1]) == len(before[1]) + 1
        assert len(after[2]) == len(before[2]) + 1
        assert after[3:] == before[3:]
        assert len([c for c in after[1] if c.result.enrichment_version == "3.0.0"]) == 1


@pytest.mark.parametrize("base", ["L", "F"])
@pytest.mark.parametrize("decision", ["ACCEPT", "REJECT"])
def test_f05_release_roundtrip_postgres(engine, tmp_path, base, decision):
    from test_f05_release_http import test_release_http

    test_release_http(engine, tmp_path, base, decision)


@pytest.mark.parametrize("base", ["L", "F"])
def test_f05_reoffer_postgres(engine, tmp_path, base):
    from test_f05_release_http import test_resume_rebinds_only_requested_pending_intent

    test_resume_rebinds_only_requested_pending_intent(engine, tmp_path, base)


def test_f05_d2_authorized_release_postgres(engine, tmp_path):
    from test_f05_durable_compatibility import (
        test_original_unknown_requires_actual_keep_accept_to_discharge,
    )

    test_original_unknown_requires_actual_keep_accept_to_discharge(engine, tmp_path)


@pytest.mark.parametrize("base", ["L", "F"])
def test_f05_competing_scoped_decisions_postgres(engine, tmp_path, base):
    from concurrent.futures import ThreadPoolExecutor

    from test_f04_http import f04_session
    from test_f05_admission import rows
    from test_f05_release_http import consent_payload, pending_fixture

    with f04_session(engine, tmp_path) as ctx:
        current, offer = pending_fixture(ctx, base)
        requests = [consent_payload(ctx, current, offer, d) for d in ("ACCEPT", "REJECT")]
        before = rows(ctx)
        path = f"/v1/sessions/{ctx.sid}/prompt-enrichment/clarification-answers"
        with ThreadPoolExecutor(max_workers=2) as pool:
            responses = tuple(
                pool.map(lambda p: ctx.client.post(path, headers=ctx.headers, json=p), requests)
            )
        assert sorted(r.status_code for r in responses) == [200, 409], [r.json() for r in responses]
        after = rows(ctx)
        assert len(after[1]) == len(before[1]) + 1
        assert len(after[2]) == len(before[2]) + 1
        assert len(after[3]) == len(before[3]) + 1
        winner = next(r for r in responses if r.status_code == 200)
        assert after[0].design.center_stone.shape.value in {"oval", "emerald_cut"}
        assert winner.json()["current_state"]["current_frame"]["revision_id"] == str(
            after[0].revision_id
        )


@pytest.mark.parametrize("base", ["L", "F"])
@pytest.mark.parametrize("availability", ["required", "explicit"])
def test_f05_schema11_release_state_roundtrip_postgres(engine, tmp_path, base, availability):
    from test_f05_release_http import test_schema11_all_additive_wrappers_survive_actual_release

    test_schema11_all_additive_wrappers_survive_actual_release(engine, tmp_path, base, availability)


@pytest.mark.parametrize("base", ["L", "F"])
def test_f05_release_fault_rollback_postgres(engine, tmp_path, base):
    from test_f05_release_http import (
        test_release_plan_insert_failure_rolls_back_revision_answer_and_cycle,
    )

    test_release_plan_insert_failure_rolls_back_revision_answer_and_cycle(engine, tmp_path, base)
