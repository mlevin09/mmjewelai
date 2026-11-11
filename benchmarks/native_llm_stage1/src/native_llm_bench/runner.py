"""Sequential multi-turn execution. This module never imports the offline gold importer."""

import base64
import hashlib
from pathlib import Path

from . import storage
from .contracts import digest, execution_plan, load, require
from .instructions import PROVENANCE_FIELDS, system_instruction
from .transport import now, parse_response, request

UNCERTAIN = {"TIMEOUT", "TRANSPORT", "INTERRUPTED_UNKNOWN"}
RETRYABLE = {"ENDPOINT_UNAVAILABLE", "SERVER_ERROR"}


def _validate_result(req, result):
    require(req["request_sha256"] == digest(req["payload"]), "request payload integrity mismatch")
    for key in ("session_id", "turn_id", "attempt", "request_sha256"):
        require(result.get(key) == req[key], "result scope/hash mismatch")
    raw = base64.b64decode(result["raw_response_base64"], validate=True)
    require(
        hashlib.sha256(raw).hexdigest() == result["raw_response_sha256"],
        "raw response integrity mismatch",
    )
    if result["status"] == "COMPLETED":
        check = {"status": None, "metrics": {}}
        parse_response(check, raw)
        require(
            check["status"] == "COMPLETED"
            and check["assistant_message"] == result["assistant_message"]
            and check["provider_response_id"] == result["provider_response_id"],
            "completed response integrity mismatch",
        )


def _unknown(req):
    return {
        "session_id": req["session_id"],
        "turn_id": req["turn_id"],
        "attempt": req["attempt"],
        "request_sha256": req["request_sha256"],
        "status": "INTERRUPTED_UNKNOWN",
        "started_at": req["recorded_at"],
        "ended_at": now(),
        "wall_seconds": None,
        "http_status": None,
        "provider_may_have_executed": True,
        "exception_family": "process_interrupted_after_request_record",
        "raw_response_base64": "",
        "raw_response_sha256": hashlib.sha256(b"").hexdigest(),
        "assistant_message": None,
        "provider_response_id": None,
        "response_json": None,
        "finish_reason": None,
        "truncated": None,
        "metrics": None,
    }


def execute(
    corpus,
    config,
    manifest,
    root,
    *,
    seed=20261111,
    selected=None,
    exclude_holdouts=False,
    resume=None,
    retry_uncertain=False,
    rerun_of=None,
    instruction_override=None,
    transport=request,
):
    plan = execution_plan(
        corpus,
        config,
        manifest,
        seed,
        selected,
        exclude_holdouts,
        instruction_override=instruction_override,
    )
    require(not (resume and rerun_of), "resume and rerun are distinct operations")
    prior = storage.read_run(rerun_of) if rerun_of else None
    if resume:
        directory = Path(resume)
        run = storage.read_run(directory)
        require(run["plan"] == plan, "resume corpus/configuration/selection mismatch")
        require(
            run["runner"]["source_sha256"] == storage.identity()["source_sha256"],
            "resume runner source mismatch",
        )
    else:
        directory, run = storage.create(root, plan)
        if prior:
            storage.write(
                directory / "rerun.json",
                {"prior_run_id": prior["run_id"], "prior_plan_sha256": prior["plan_sha256"]},
            )
    summary = {
        "run_id": run["run_id"],
        "run_directory": str(directory),
        "status": "RUNNING",
        "sessions": {},
        "plan_sha256": run["plan_sha256"],
    }
    sessions = {s["session_id"]: s for s in corpus["sessions"]}
    response_owners = {}
    with storage.lock(directory):
        # Recovery authorization is append-only too; it is not a silent plan/config change.
        recovery = {"at": now(), "retry_uncertain": retry_uncertain, "resume": bool(resume)}
        import uuid

        storage.write(directory / "invocations" / (uuid.uuid4().hex + ".json"), recovery)
        storage.read_results(directory)
        try:
            for sid in plan["session_order"]:
                session = sessions[sid]
                system, provenance = system_instruction(corpus, session, plan)
                history = [{"role": "system", "content": system}]
                state = {
                    "status": "COMPLETED",
                    "completed_turns": 0,
                    "total_turns": len(session["turns"]),
                    "turn_statuses": {t["turn_id"]: "NOT_EXECUTED" for t in session["turns"]},
                }
                summary["sessions"][sid] = state
                for index, turn in enumerate(session["turns"]):
                    tid = turn["turn_id"]
                    messages = [*history, {"role": "user", "content": turn["text"]}]
                    payload = config.payload(messages)
                    count = storage.attempts(directory, sid, tid)
                    require(count <= config.max_attempts, "journal exceeds attempt budget")
                    completed = None
                    last = None
                    for number in range(1, count + 1):
                        req_path, res_path = storage.files(directory, sid, tid, number)
                        req = load(req_path)
                        require(
                            req["session_id"] == sid
                            and req["turn_id"] == tid
                            and req["attempt"] == number
                            and req["turn_index"] == index + 1
                            and req["payload"] == payload
                            and req["request_sha256"] == digest(payload)
                            and {k: req[k] for k in PROVENANCE_FIELDS if k in req} == provenance,
                            "source/history/request integrity mismatch",
                        )
                        if not res_path.exists():
                            storage.write(res_path, _unknown(req))
                        last = load(res_path)
                        _validate_result(req, last)
                        if last["status"] == "COMPLETED":
                            require(
                                number == count and completed is None, "duplicate completed attempt"
                            )
                            completed = last
                    while completed is None and count < config.max_attempts:
                        if last is not None and last["status"] not in RETRYABLE:
                            if not (retry_uncertain and last["status"] in UNCERTAIN):
                                break
                        count += 1
                        req_path, res_path = storage.files(directory, sid, tid, count)
                        req = {
                            "session_id": sid,
                            "turn_id": tid,
                            "turn_index": index + 1,
                            "attempt": count,
                            "recorded_at": now(),
                            "payload": payload,
                            "request_sha256": digest(payload),
                            **provenance,
                        }
                        storage.write(req_path, req)
                        state["turn_statuses"][tid] = "IN_FLIGHT_OUTCOME_UNKNOWN"
                        last = transport(config, payload)
                        last.update(
                            {
                                k: req[k]
                                for k in ("session_id", "turn_id", "attempt", "request_sha256")
                            }
                        )
                        rid = last.get("provider_response_id")
                        if rid and rid in response_owners and response_owners[rid] != sid:
                            last["status"] = "SUSPECTED_CONTEXT_LEAKAGE"
                        storage.write(res_path, last)
                        _validate_result(req, last)
                        if last["status"] == "COMPLETED":
                            completed = last
                    if completed is None:
                        state["status"] = last["status"] if last else "INTERRUPTED_UNKNOWN"
                        state["blocked_turn_id"] = tid
                        state["turn_statuses"][tid] = state["status"]
                        # Later requests after a failed prefix are not legitimate history.
                        for later in session["turns"][index + 1 :]:
                            state["turn_statuses"][later["turn_id"]] = "BLOCKED_BY_PRIOR_TURN"
                            require(
                                storage.attempts(directory, sid, later["turn_id"]) == 0,
                                "journal continues after failed prefix",
                            )
                        break
                    rid = completed["provider_response_id"]
                    require(
                        rid not in response_owners or response_owners[rid] == sid,
                        "suspected cross-session response reuse",
                    )
                    response_owners[rid] = sid
                    history = [*messages, completed["assistant_message"]]
                    state["completed_turns"] += 1
                    state["turn_statuses"][tid] = "COMPLETED"
            summary["status"] = (
                "COMPLETED"
                if all(s["status"] == "COMPLETED" for s in summary["sessions"].values())
                else "INCOMPLETE"
            )
        except BaseException:
            summary["status"] = "INTERRUPTED"
            raise
        finally:
            summary["updated_at"] = now()
            storage.write(directory / "summary.json", summary, replace=True)
    return summary
