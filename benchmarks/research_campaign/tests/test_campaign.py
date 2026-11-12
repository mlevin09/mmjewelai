import copy
import json
import sqlite3

import pytest
from conftest import hypothesis, queue, register
from native_llm_bench import storage
from native_llm_bench.contracts import InvalidArtifact, digest, load, sha256_file

from jewelai_research.contracts import PROFILES, TARGET, Inputs, experiment_plan, validate_envelope
from jewelai_research.controller import Controller
from jewelai_research.mcp import Principal
from jewelai_research.worker import Worker


def call(f, name, **kw):
    return f.c.call(f.principal, name, {"campaign_id": f.envelope["campaign_id"], **kw})


def test_real_mcp_adaptive_campaign_one_assignment_three_types_and_budget_stop(campaign, wire):
    f, cid = campaign, campaign.envelope["campaign_id"]
    original = [sha256_file(p) for p in f.inputs.paths]
    assert (
        wire.rpc("initialize", {"protocolVersion": "2025-06-18"})[1]["result"]["serverInfo"][
            "version"
        ]
        == "1.0.0"
    )
    names = {t["name"] for t in wire.rpc("tools/list")[1]["result"]["tools"]}
    assert len(names) == 7 and "stop_campaign" in names

    def tool(name, **kwargs):
        status, response = wire.rpc(
            "tools/call", {"name": name, "arguments": {"campaign_id": cid, **kwargs}}
        )
        assert status == 200
        return response

    # Synthetic reasoning driver, not a fixed C0/C1 optimizer. Choice branches on actual
    # tool-visible results. Real Workspace reasoning/lifetime is a distinct connection gate.
    choices, evidence = [], []
    profile = "NATIVE_CONTROL_V1"
    for n in range(1, 4):
        eid = f"E{n}"
        registered = tool(
            "propose_and_register_experiment",
            experiment_id=eid,
            profile=profile,
            sessions=["SYN2"],
            hypothesis=hypothesis(*evidence),
            idempotency_key="register-" + eid,
        )
        assert "error" not in registered
        queued = tool(
            "execute_registered_experiment", experiment_id=eid, idempotency_key="execute-" + eid
        )
        assert queued["result"]["structuredContent"]["status"] == "QUEUED"
        # Separate worker instance: execution is independent of MCP request/Agent lifetime.
        worker = Worker(
            Controller(f.c.ledger.root, f.inputs, clock=lambda: f.clock[0]), f.lab, f.model
        )
        worker.once(cid)
        result = tool("get_experiment_results", experiment_id=eid)["result"]["structuredContent"]
        measured = result["receipt"]["measurements"]
        choices.append((profile, measured))
        evidence.append(eid)
        if measured["truncated"]:
            profile = "SAMPLING_LOW_TEMP_V1"
        elif measured["completed"] == 2:
            profile = "BREVITY_POLICY_V1"
        else:
            break
    assert [c[0] for c in choices] == list(PROFILES)
    assert [c[1]["completed"] for c in choices] == [0, 2, 2]
    denied = tool(
        "propose_and_register_experiment",
        experiment_id="E4",
        profile=profile,
        sessions=["SYN2"],
        hypothesis=hypothesis(*evidence),
        idempotency_key="register-E4",
    )
    assert denied["error"]["message"] == "campaign_budget_exhausted"
    tool("stop_campaign", reason="hard reservation reached", idempotency_key="stop")
    f.worker.once(cid)
    report = tool(
        "finalize_campaign",
        conclusion="Synthetic exploration stopped at the hard cap.",
        idempotency_key="final",
    )["result"]["structuredContent"]
    assert report["report"]["cleanup"]["verified_stopped"]
    assert len(report["report"]["experiments"]) == 3
    assert report["report"]["limits"]["reserved_proxy_cost"] == 9
    assert f.lab.current == "TERMINATED" and f.lab.starts == 3
    assert len(f.model.calls) == 5  # one truncated prefix, then two complete two-turn studies
    assert "NEVER_IN_MODEL_PAYLOAD" not in json.dumps(f.model.calls)
    assert [sha256_file(p) for p in f.inputs.paths] == original
    assert digest(json.loads(f.c.verify_report(cid))) == digest(report["report"])
    same = tool(
        "finalize_campaign",
        conclusion="Synthetic exploration stopped at the hard cap.",
        idempotency_key="final",
    )["result"]["structuredContent"]
    assert same == report
    ledger = tool("list_ledger", offset=0, limit=100)["result"]["structuredContent"]
    assert sum(e["kind"] == "FINALIZED" for e in ledger["events"]) == 1
    assert len([e for e in ledger["events"] if e["kind"] == "REGISTERED"]) == 3
    # Optional private receipt export for coordinator review; no customer/model data.
    # A fresh directory is required: never overwrite a previous qualification campaign.
    import os
    from pathlib import Path

    if destination := os.environ.get("JEWELAI_RESEARCH_TEST_EVIDENCE"):
        destination = Path(destination)
        destination.mkdir(mode=0o700, parents=True, exist_ok=False)
        storage.write(destination / "synthetic-report.json", report)
        storage.write(destination / "synthetic-ledger.json", ledger)
        storage.write(
            destination / "qualification.json",
            {
                "mode": "SYNTHETIC",
                "tool_names": sorted(names),
                "experiment_types": choices,
                "actual_attempts": len(f.model.calls),
                "reserved_attempts": 6,
                "budget_refusal": denied,
                "cleanup_verified": True,
                "report_byte_sha256": report["report_sha256"],
                "source_pins": f.inputs.pins(),
                "live_workspace": "NOT_VERIFIED",
                "live_gcp": "NOT_EXECUTED",
            },
        )


@pytest.mark.parametrize(
    "alter",
    [
        lambda e: e["target"].update(vm="other"),
        lambda e: e["pins"].update(corpus_sha256="0" * 64),
        lambda e: e["pins"].update(runner_sha256="0" * 64),
        lambda e: e.update(allowed_profiles=["shell"]),
        lambda e: e.update(allowed_sessions=["KG09"]),
        lambda e: e.update(allowed_sessions=["G26"]),
        lambda e: e.update(command="rm -rf /"),
        lambda e: e.update(period_end=e["period_start"]),
        lambda e: e["budget"].update(hard_ceiling=0),
        lambda e: e["budget"].update(unit="USD_exact"),
    ],
)
def test_envelope_rejects_forbidden_or_tampered_inputs(campaign, alter):
    e = copy.deepcopy(campaign.envelope)
    alter(e)
    with pytest.raises(InvalidArtifact):
        validate_envelope(e, campaign.inputs)
    assert campaign.lab.starts == 0


@pytest.mark.parametrize(
    "field,value",
    [
        ("gold", "REWRITE"),
        ("command", "echo unsafe"),
        ("vm", "another"),
        ("instruction", "injected"),
    ],
)
def test_no_tool_escape_hatches(campaign, wire, field, value):
    _, response = wire.rpc(
        "tools/call",
        {
            "name": "propose_and_register_experiment",
            "arguments": {
                "campaign_id": campaign.envelope["campaign_id"],
                "experiment_id": "E1",
                "idempotency_key": "k",
                "profile": "NATIVE_CONTROL_V1",
                "sessions": ["SYN2"],
                "hypothesis": hypothesis(),
                field: value,
            },
        },
    )
    assert "error" in response and not campaign.model.calls


def test_holdout_cannot_be_laundered_by_false_flag_or_turn_alias(campaign):
    f = campaign
    corpus = load(f.inputs.paths[0])
    corpus["sessions"][0]["turns"][0]["turn_id"] = "J35"
    f.inputs.paths[0].write_text(json.dumps(corpus))
    inputs = Inputs(*f.inputs.paths)
    e = copy.deepcopy(f.envelope)
    e["pins"] = inputs.pins()
    with pytest.raises(InvalidArtifact, match="holdout"):
        validate_envelope(e, inputs)


def test_separate_seeds_exact_plan_and_policy_label(campaign):
    f = campaign
    cfg, override, plan = experiment_plan(f.envelope, f.inputs, "BREVITY_POLICY_V1", ["SYN2"])
    assert plan["scheduling_seed"] == 123 and cfg.seed == 456
    assert override["profile_id"].startswith("NB09D")
    assert plan["holdout_sessions_selected"] == []
    assert PROFILES["BREVITY_POLICY_V1"]["type"] == "policy_template"


def test_idempotent_register_execute_no_repeat_paid_attempt(campaign):
    f = campaign
    first = register(f)
    assert register(f) == first
    assert queue(f) == queue(f)
    f.worker.once(f.envelope["campaign_id"])
    count = len(f.model.calls)
    assert queue(f)["status"] == "QUEUED"  # receipt replay, not another queue entry
    assert f.worker.once(f.envelope["campaign_id"]) == "IDLE"
    assert len(f.model.calls) == count
    with pytest.raises(InvalidArtifact, match="idempotency_conflict"):
        register(f, profile="SAMPLING_LOW_TEMP_V1")


def test_unknown_crash_recovery_no_retry_and_full_cost_retained(campaign):
    f = campaign
    x = register(f)
    queue(f)
    _, _, plan = experiment_plan(f.envelope, f.inputs, x["profile"], x["sessions"])
    directory, run = storage.create(f.c.directory(f.envelope["campaign_id"]) / "runs", plan)
    # Reproduce durable claim + request followed by process death (no result/summary).
    with f.c.ledger.transaction() as db:
        f.c.ledger.append(
            db,
            f.envelope["campaign_id"],
            "RUNNING",
            {"experiment_id": "E1", "status": "RUNNING", "run_id": run["run_id"]},
        )
    from native_llm_bench.instructions import system_instruction

    cfg, _, _ = experiment_plan(f.envelope, f.inputs, x["profile"], x["sessions"])
    session = f.inputs.corpus["sessions"][0]
    system, _ = system_instruction(f.inputs.corpus, session, plan)
    payload = cfg.payload(
        [
            {"role": "system", "content": system},
            {"role": "user", "content": session["turns"][0]["text"]},
        ]
    )
    req, _ = storage.files(directory, "SYN2", "SYN2.T1", 1)
    storage.write(
        req,
        {
            "session_id": "SYN2",
            "turn_id": "SYN2.T1",
            "attempt": 1,
            "turn_index": 1,
            "payload": payload,
            "request_sha256": digest(payload),
        },
    )
    restarted = Worker(
        Controller(f.c.ledger.root, f.inputs, clock=lambda: f.clock[0]), f.lab, f.model
    )
    assert restarted.once(f.envelope["campaign_id"]) == "RECOVERED_UNKNOWN"
    result = call(f, "get_experiment_results", experiment_id="E1")
    assert result["status"] == "UNKNOWN" and len(f.model.calls) == 0
    assert result["receipt"]["reserved_attempts_charged"] == 2
    assert call(f, "campaign_status")["limits"]["reserved_proxy_cost"] == 5
    assert f.lab.current == "TERMINATED"


def test_timeout_does_not_refund_or_auto_retry(campaign):
    f = campaign
    register(f)
    queue(f)

    def timeout(cfg, payload):
        r = f.model(cfg, payload)
        r.update(status="TIMEOUT", assistant_message=None, metrics={}, wall_seconds=None)
        return r

    assert Worker(f.c, f.lab, timeout).once(f.envelope["campaign_id"]) == "INCOMPLETE"
    r = call(f, "get_experiment_results", experiment_id="E1")
    assert r["receipt"]["measurements"]["statuses"] == {"TIMEOUT": 1}
    assert r["receipt"]["reserved_attempts_charged"] == 2
    assert len(f.model.calls) == 1 and f.lab.current == "TERMINATED"


def test_deadline_emergency_stop_and_unverified_cleanup_block_finalization(campaign):
    f = campaign
    register(f)
    queue(f)
    f.clock[0] += 601
    assert f.worker.once(f.envelope["campaign_id"]) == "STOPPED"
    assert not f.model.calls
    assert call(f, "get_experiment_results", experiment_id="E1")["status"] == "STOPPED"
    f.lab.current = "RUNNING"  # no campaign-owned lease: must never stop this instance
    f.worker.once(f.envelope["campaign_id"])
    with pytest.raises(InvalidArtifact, match="cleanup_not_verified"):
        call(f, "finalize_campaign", idempotency_key="final", conclusion="Stopped.")


def test_stop_during_execution_prevents_next_turn_and_verifies_cleanup(campaign):
    f = campaign
    register(f, profile="SAMPLING_LOW_TEMP_V1")
    queue(f)

    def stop_after_one(cfg, payload):
        result = f.model(cfg, payload)
        call(f, "stop_campaign", idempotency_key="stop", reason="emergency")
        return result

    assert Worker(f.c, f.lab, stop_after_one).once(f.envelope["campaign_id"]) == "STOPPED"
    assert len(f.model.calls) == 1 and f.lab.current == "TERMINATED"


def test_append_only_integrity_and_receipt_tampering(campaign):
    f = campaign
    register(f)
    queue(f)
    f.worker.once(f.envelope["campaign_id"])
    with f.c.ledger.transaction() as db, pytest.raises(sqlite3.IntegrityError, match="append only"):
        db.execute("UPDATE events SET kind='DELETED'")
    path = f.c.directory(f.envelope["campaign_id"]) / "E1.receipt.json"
    path.write_text("{}")
    with pytest.raises(InvalidArtifact, match="receipt_integrity"):
        call(f, "get_experiment_results", experiment_id="E1")


@pytest.mark.parametrize(
    "subject,scopes",
    [("intruder", ["campaign.execute"]), ("synthetic-researcher", ["campaign.read"])],
)
def test_subject_scope_authorization(campaign, subject, scopes):
    f = campaign
    with pytest.raises(InvalidArtifact):
        f.c.call(
            Principal(subject, frozenset(scopes)),
            "stop_campaign",
            {"campaign_id": f.envelope["campaign_id"], "idempotency_key": "stop", "reason": "x"},
        )
    assert not call(f, "campaign_status")["stopped"]


def test_wrong_live_gate_cannot_be_waived_by_agent_prose(campaign):
    f = campaign
    e = copy.deepcopy(f.envelope)
    e["mode"] = "LIVE"
    from jewelai_research.contracts import MODEL, MODEL_SHA, RUNTIME_COMMIT, RUNTIME_SHA

    m = load(f.inputs.paths[1])
    m.update(
        model_id=MODEL,
        model_sha256=MODEL_SHA,
        runtime_sha256=RUNTIME_SHA,
        runtime_commit=RUNTIME_COMMIT,
        verification_status="HISTORICAL_NOT_REVERIFIED",
    )
    f.inputs.paths[1].write_text(json.dumps(m))
    inputs = Inputs(*f.inputs.paths)
    e["pins"] = inputs.pins()
    e["budget"]["billing_guarantee"] = "OWNER SAYS ALL ALLOWED"
    with pytest.raises(InvalidArtifact, match="live_activation_blocked"):
        validate_envelope(e, inputs)
    assert f.lab.starts == 0 and e["target"] == TARGET


def test_source_change_after_queue_fails_before_start_and_cleans_up(campaign):
    f = campaign
    register(f)
    queue(f)
    f.inputs.paths[2].write_text("tampered gold")
    assert f.worker.once(f.envelope["campaign_id"]) == "UNKNOWN"
    assert f.lab.starts == 0 and f.lab.stops == 0 and not f.model.calls


def test_global_concurrency_one(campaign):
    import fcntl
    import os

    f = campaign
    register(f)
    queue(f)
    fd = os.open(f.c.ledger.root / ".worker.lock", os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(InvalidArtifact, match="worker_already_active"):
            f.worker.once(f.envelope["campaign_id"])
    finally:
        os.close(fd)
    assert not f.model.calls


@pytest.mark.parametrize(
    "limit,value", [("max_experiments", 1), ("max_turns", 2), ("max_attempts", 2)]
)
def test_each_independent_campaign_cap_is_enforced(campaign, tmp_path, limit, value):
    f = campaign
    e = copy.deepcopy(f.envelope)
    e[limit] = value
    c = Controller(tmp_path / (limit + "-private"), f.inputs, clock=lambda: f.clock[0])
    c.activate(e)
    f.c = c
    register(f)
    with pytest.raises(InvalidArtifact, match="campaign_budget_exhausted"):
        register(f, eid="E2")
    assert call(f, "campaign_status")["limits"]["experiments"] == 1


def test_failed_unowned_start_does_not_stop_or_log_raw_error(campaign):
    f = campaign
    register(f)
    queue(f)

    def fail(_, journal):
        raise RuntimeError("PRIVATE_PROVIDER_BODY_AND_TOKEN")

    f.lab.start = fail
    assert f.worker.once(f.envelope["campaign_id"]) == "UNKNOWN"
    assert f.lab.stops == 0 and not f.model.calls
    events = call(f, "list_ledger", offset=0, limit=100)
    assert "PRIVATE_PROVIDER_BODY_AND_TOKEN" not in json.dumps(events)
    assert "PRIVATE_PROVIDER_BODY_AND_TOKEN" not in json.dumps(
        call(f, "get_experiment_results", experiment_id="E1")
    )


def test_raw_journal_tamper_blocks_result_and_final_report(campaign):
    f = campaign
    register(f)
    queue(f)
    f.worker.once(f.envelope["campaign_id"])
    result = call(f, "get_experiment_results", experiment_id="E1")
    run_dir = f.c.directory(f.envelope["campaign_id"]) / "runs" / result["run_id"]
    req, _ = storage.files(run_dir, "SYN2", "SYN2.T1", 1)
    original = load(req)
    original["payload"]["messages"][-1]["content"] = "tampered"
    original["request_sha256"] = digest(original["payload"])
    req.write_text(json.dumps(original))
    with pytest.raises(InvalidArtifact, match="raw_journal_changed"):
        call(f, "get_experiment_results", experiment_id="E1")
    with pytest.raises(InvalidArtifact, match="raw_journal_changed"):
        call(f, "finalize_campaign", idempotency_key="f", conclusion="Must not certify tamper")


def test_recovery_cleanup_runs_even_when_raw_evidence_is_corrupt(campaign):
    f = campaign
    x = register(f)
    queue(f)
    _, _, plan = experiment_plan(f.envelope, f.inputs, x["profile"], x["sessions"])
    directory, run = storage.create(f.c.directory(f.envelope["campaign_id"]) / "runs", plan)
    with f.c.ledger.transaction() as db:
        f.c.ledger.append(
            db,
            f.envelope["campaign_id"],
            "RUNNING",
            {"experiment_id": "E1", "status": "RUNNING", "run_id": run["run_id"]},
        )
    (directory / "run.json").write_text("{}")
    from jewelai_research.leases import LeaseJournal

    f.lab.start(f.envelope, LeaseJournal(f.c, f.envelope["campaign_id"]))
    with pytest.raises((InvalidArtifact, KeyError)):
        f.worker.once(f.envelope["campaign_id"])
    assert f.lab.current == "TERMINATED" and f.lab.stops == 1
    assert not f.model.calls


def test_counterfactual_results_change_next_experiment_type(campaign, wire):
    f, cid = campaign, campaign.envelope["campaign_id"]
    f.model.truncate_control = False
    register(f)
    queue(f)
    f.worker.once(cid)
    response = wire.rpc(
        "tools/call",
        {
            "name": "get_experiment_results",
            "arguments": {"campaign_id": cid, "experiment_id": "E1"},
        },
    )[1]["result"]["structuredContent"]
    # Unlike the truncated-control E2E, the next research type skips sampling.
    profile = (
        "SAMPLING_LOW_TEMP_V1" if response["measurements"]["truncated"] else "BREVITY_POLICY_V1"
    )
    assert profile == "BREVITY_POLICY_V1"
    register(f, eid="E2", profile=profile, evidence=["E1"])
    queue(f, "E2")
    f.worker.once(cid)
    assert call(f, "get_experiment_results", experiment_id="E2")["status"] == "COMPLETED"
