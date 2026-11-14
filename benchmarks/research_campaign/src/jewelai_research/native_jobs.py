"""Narrow connection to the existing native Runner; no experiment-selection logic.

The authenticated transport supplies subject. Arguments cannot select a VM, shell,
path, endpoint, identity, source artifact, spending approval or execution limit.
"""

import base64
import hashlib
import time
from dataclasses import replace

from native_llm_bench import storage
from native_llm_bench.contracts import Config, digest, execution_plan, keys, require

from .contracts import bounded_text, identifier, reserved
from .ledger import Ledger

PARAMETERS = {
    "temperature",
    "top_p",
    "top_k",
    "min_p",
    "presence_penalty",
    "repeat_penalty",
    "max_tokens",
    "timeout_seconds",
    "seed",
}
READ_SCOPE = "jewelai.research.runner.read"
EXECUTE_SCOPE = "jewelai.research.runner.execute"
TOOLS = {
    "native_runner_catalog": {},
    "native_runner_vm_status": {},
    "native_runner_start": {},
    "native_runner_stop": {},
    "native_runner_finish": {
        "outcome": {"type": "string", "enum": ["completed", "failed", "cancelled"]},
        "report": {"type": "string", "maxLength": 32000},
    },
    "native_runner_submit": {
        "idempotency_key": {"type": "string", "maxLength": 80},
        "sessions": {"type": "array", "items": {"type": "string"}, "maxItems": 20},
        "parameters": {"type": "object", "additionalProperties": True},
        "hypothesis": {"type": "string", "maxLength": 4000},
    },
    "native_runner_status": {"job_id": {"type": "string", "maxLength": 64}},
    "native_runner_result": {
        "job_id": {"type": "string", "maxLength": 64},
        "offset": {"type": "integer", "minimum": 0},
    },
}


class NativeRunnerActions:
    def __init__(
        self,
        access,
        inputs,
        guest_paths,
        *,
        guest_ready=False,
        clock=time.time,
        refresh_approval=None,
    ):
        keys(guest_paths, ("runtime", "manifest"))
        self.access, self.inputs = access, inputs
        self.paths, self.ready, self.clock = dict(guest_paths), guest_ready, clock
        self.refresh_approval = refresh_approval
        # Existing append-only SQLite primitive; separate namespace, no campaign controller.
        self.ledger = Ledger(access.root / "native-runner")

    def _inputs(self):
        require(
            [storage_path_sha(p) for p in self.inputs.paths] == self.inputs.file_hashes
            and storage.identity()["source_sha256"] == self.inputs.runner_sha,
            "native_runner_source_changed",
        )

    def _permit(self):
        if self.refresh_approval is not None:
            self.refresh_approval()
        approval = self.access.lease.authorized()
        if approval.get("shutdown_policy") == "completion":
            with self.ledger.transaction() as db:
                require(
                    not any(
                        e["kind"] == "FINISH"
                        and e["body"]["operation_id"] == approval["operation_id"]
                        for e in self.ledger.read(db, "native-runner")
                    ),
                    "research_operation_already_finished",
                )
            return approval, None
        limits = approval.get("native_runner")
        require(isinstance(limits, dict), "native_runner_not_approved")
        keys(limits, ("maximum_jobs", "maximum_turns", "maximum_job_seconds", "approved_usd"))
        for name, maximum in (
            ("maximum_jobs", 100),
            ("maximum_turns", 1000),
            ("maximum_job_seconds", 900),
        ):
            require(
                type(limits[name]) is int and 0 < limits[name] <= maximum, "invalid_runner_limit"
            )
        import math

        require(
            type(limits["approved_usd"]) in (int, float)
            and math.isfinite(limits["approved_usd"])
            and limits["approved_usd"] > 0,
            "explicit_spending_approval_required",
        )
        # This is Owner authorization plus count/time ceilings, NOT a billing cap.
        return approval, limits

    def call(self, principal, name, args):
        require(name in TOOLS, "unknown_native_runner_action")
        keys(args, TOOLS[name])
        require(READ_SCOPE in principal.scopes, "native_runner_scope_required")
        bounded_text(principal.subject, 200)
        if name in {
            "native_runner_start",
            "native_runner_submit",
            "native_runner_stop",
            "native_runner_finish",
        }:
            require(EXECUTE_SCOPE in principal.scopes, "native_runner_execution_scope_required")
        if name == "native_runner_stop":
            return self.access.call(
                "vm_stop", {}
            )  # Existing ownership-fenced cleanup, even expired.
        if name == "native_runner_vm_status":
            return self.access.call("vm_status", {})
        self._inputs()
        if name == "native_runner_catalog":
            return {
                "sessions": [
                    {"id": s["session_id"], "language": s["language"], "turns": len(s["turns"])}
                    for s in self.inputs.corpus["sessions"]
                    if not reserved(s)
                ],
                "parameter_names": sorted(PARAMETERS),
                "pins": {
                    "runtime": self.inputs.file_hashes[0],
                    "manifest": self.inputs.file_hashes[1],
                    "runner": self.inputs.runner_sha,
                },
                "guest_installed_and_verified": self.ready,
                "automatic_selection": False,
            }
        if name == "native_runner_start":
            self._permit()
            require(self.ready is True, "native_runner_guest_not_verified")
            return self.access.call("vm_start", {})
        if name == "native_runner_submit":
            return self._submit(principal.subject, args)
        if name == "native_runner_finish":
            return self._finish(principal.subject, args)
        identifier(args["job_id"])
        with self.ledger.transaction() as db:
            events = self.ledger.read(db, "native-runner")
            original = next(
                (
                    e["body"]
                    for e in events
                    if e["kind"] == "RESERVED" and e["body"]["job_id"] == args["job_id"]
                ),
                None,
            )
            require(original and original["subject"] == principal.subject, "native_job_not_found")
            archived = next(
                (
                    j
                    for e in events
                    if e["kind"] == "FINISH"
                    for j in e["body"]["jobs"]
                    if j["job_id"] == args["job_id"]
                ),
                None,
            )
        if archived:
            if name == "native_runner_status":
                return self._public(archived["receipt"])
            path = self.ledger.root / (args["job_id"] + ".export.json")
            require(
                archived.get("export_sha256")
                and path.is_file()
                and storage_path_sha(path) == archived["export_sha256"],
                "native_export_integrity",
            )
            offset = args["offset"]
            require(
                type(offset) is int and 0 <= offset <= path.stat().st_size, "invalid_result_offset"
            )
            with path.open("rb") as stream:
                stream.seek(offset)
                chunk = stream.read(12288)
            return {
                "job_id": args["job_id"],
                "sha256": archived["export_sha256"],
                "total_bytes": path.stat().st_size,
                "offset": offset,
                "next_offset": offset + len(chunk),
                "data_base64": base64.b64encode(chunk).decode(),
                "eof": offset + len(chunk) >= path.stat().st_size,
            }
        with self.access.locked():
            if name == "native_runner_status":
                result = self.access._guest("native_status", {"job_id": args["job_id"]})
                require(result["job_id"] == args["job_id"], "native_job_scope_mismatch")
                require(
                    result.get("plan_sha256") == original["plan_sha256"]
                    and result.get("runner_sha256") == original["runner_sha256"],
                    "native_job_pin_mismatch",
                )
                require(
                    result.get("status") in {"RUNNING", "COMPLETED", "INCOMPLETE", "UNKNOWN"},
                    "invalid_native_job_status",
                )
                with self.ledger.transaction() as db:
                    self.ledger.append(db, "native-runner", "STATUS", result)
                return self._public(result)
            require(
                type(args["offset"]) is int and 0 <= args["offset"] <= 8 * 1024**2,
                "invalid_result_offset",
            )
            result = self.access._guest("native_result", args)
            require(result["job_id"] == args["job_id"], "native_job_scope_mismatch")
            chunk = base64.b64decode(result["data_base64"], validate=True)
            require(len(chunk) <= 12288, "native_result_too_large")
            # Pin every chunk to the same immutable terminal export, including after restart.
            with self.ledger.transaction() as db:
                previous = [
                    e["body"]
                    for e in self.ledger.read(db, "native-runner")
                    if e["kind"] == "EXPORT" and e["body"]["job_id"] == args["job_id"]
                ]
                pin = {
                    "job_id": args["job_id"],
                    "sha256": result["sha256"],
                    "total_bytes": result["total_bytes"],
                }
                require(not previous or all(p == pin for p in previous), "native_export_changed")
                if not previous:
                    self.ledger.append(db, "native-runner", "EXPORT", pin)
            return result

    @staticmethod
    def _public(value):
        return {
            k: value[k]
            for k in ("job_id", "status", "plan_sha256", "runner_sha256", "summary", "reason")
            if k in value
        }

    def _submit(self, subject, args):
        identifier(args["idempotency_key"])
        bounded_text(args["hypothesis"])
        require(
            isinstance(args["parameters"], dict) and set(args["parameters"]) <= PARAMETERS,
            "unsupported_native_runner_parameter",
        )
        sessions = args["sessions"]
        require(
            isinstance(sessions, list)
            and 0 < len(sessions) <= 20
            and all(isinstance(s, str) for s in sessions)
            and len(set(sessions)) == len(sessions),
            "invalid_native_runner_sessions",
        )
        selected = [s for s in self.inputs.corpus["sessions"] if s["session_id"] in sessions]
        require(
            len(selected) == len(sessions) and not any(reserved(s) for s in selected),
            "native_runner_holdout_or_unknown_session",
        )
        cfg = replace(
            Config(
                model=self.inputs.manifest["model_id"],
                context_tokens=self.inputs.manifest["context_tokens"],
            ),
            **args["parameters"],
        )
        cfg.validate(self.inputs.manifest)
        plan = execution_plan(
            self.inputs.corpus, cfg, self.inputs.manifest, selected=sessions, exclude_holdouts=True
        )
        jid = digest({"subject": subject, "key": args["idempotency_key"]})
        request_hash = digest(args)
        with self.access.locked():
            approval, limits = self._permit()
            require(self.ready is True, "native_runner_guest_not_verified")
            with self.ledger.transaction() as db:
                events = self.ledger.read(db, "native-runner")
                old = [
                    e["body"]
                    for e in events
                    if e["body"].get("job_id") == jid and "status" in e["body"]
                ]
                if old:
                    require(old[0]["request_sha256"] == request_hash, "native_idempotency_conflict")
                    if old[-1]["status"] == "RESERVED":
                        # Crash around dispatch is outcome-unknown; NEVER resubmit automatically.
                        self.ledger.append(
                            db, "native-runner", "UNKNOWN", {"job_id": jid, "status": "UNKNOWN"}
                        )
                        return {"job_id": jid, "status": "UNKNOWN"}
                    return self._public(old[-1])
                reservations = [
                    e["body"]
                    for e in events
                    if e["kind"] == "RESERVED" and e["body"]["approval_sha256"] == digest(approval)
                ]
                latest = {}
                for event in events:
                    body = event["body"]
                    if "status" in body:
                        latest[body["job_id"]] = body["status"]
                turns = sum(len(s["turns"]) for s in selected)
                if limits is not None:
                    require(
                        len(reservations) < limits["maximum_jobs"]
                        and sum(r["reserved_turns"] for r in reservations) + turns
                        <= limits["maximum_turns"],
                        "native_runner_budget_exhausted",
                    )
                require(
                    not any(s in {"RESERVED", "RUNNING", "UNKNOWN"} for s in latest.values()),
                    "native_runner_already_busy",
                )
                deadline = (
                    None
                    if limits is None
                    else min(
                        int(approval["expires_at"]),
                        int(self.clock()) + limits["maximum_job_seconds"],
                    )
                )
                require(deadline is None or deadline > self.clock(), "native_runner_window_expired")
                record = {
                    "job_id": jid,
                    "status": "RESERVED",
                    "subject": subject,
                    "request_sha256": request_hash,
                    "approval_sha256": digest(approval),
                    "operation_id": approval.get("operation_id"),
                    "reserved_turns": turns,
                    "hypothesis": args["hypothesis"],
                    "plan_sha256": digest(plan),
                    "runner_sha256": self.inputs.runner_sha,
                }
                self.ledger.append(db, "native-runner", "RESERVED", record)
            request = {
                "job_id": jid,
                "paths": self.paths,
                "approval_sha256": digest(approval),
                "file_hashes": self.inputs.file_hashes[:2],
                "runner_sha256": self.inputs.runner_sha,
                "config": cfg.record(),
                "sessions": sessions,
                "plan_sha256": digest(plan),
                "deadline": deadline,
            }
            try:
                result = self.access._guest("native_submit", request)
                require(
                    result["job_id"] == jid and result["status"] in {"RUNNING", "COMPLETED"},
                    "native_dispatch_not_confirmed",
                )
            except Exception:
                # Bounded ambiguous I/O outcome, charged reservation, no raw SSH/provider data.
                result = {"job_id": jid, "status": "UNKNOWN", "reason": "dispatch_outcome_unknown"}
            with self.ledger.transaction() as db:
                self.ledger.append(db, "native-runner", "DISPATCH", result)
            return self._public(result)

    def _finish(self, subject, args):
        require(args["outcome"] in {"completed", "failed", "cancelled"}, "invalid_finish_outcome")
        bounded_text(args["report"], 32000)
        # The Agent declares campaign completion. A finished experiment never does so.
        with self.access.locked():
            approval, _ = self._permit()
            require(approval.get("shutdown_policy") == "completion", "completion_policy_required")
            lease = self.access.lease.read()
            require(lease and lease["phase"] == "OWNED", "owned_vm_required")
            with self.ledger.transaction() as db:
                jobs = [
                    e["body"]
                    for e in self.ledger.read(db, "native-runner")
                    if e["kind"] == "RESERVED"
                    and e["body"].get("operation_id") == approval["operation_id"]
                ]
            require(all(j["subject"] == subject for j in jobs), "native_job_not_found")
            saved = []
            for job in jobs:
                jid = job["job_id"]
                receipt = self.access._guest("native_status", {"job_id": jid})
                require(
                    receipt.get("job_id") == jid
                    and receipt.get("plan_sha256") == job["plan_sha256"]
                    and receipt.get("runner_sha256") == job["runner_sha256"],
                    "native_job_pin_mismatch",
                )
                require(receipt["status"] != "RUNNING", "native_runner_still_active")
                if args["outcome"] == "completed":
                    require(
                        receipt["status"] in {"COMPLETED", "INCOMPLETE"}, "native_job_unresolved"
                    )
                with self.ledger.transaction() as db:
                    self.ledger.append(db, "native-runner", "STATUS", receipt)
                item = {"job_id": jid, "receipt": receipt}
                if receipt.get("export_sha256"):
                    raw, offset = bytearray(), 0
                    while True:
                        chunk = self.access._guest(
                            "native_result", {"job_id": jid, "offset": offset}
                        )
                        data = base64.b64decode(chunk["data_base64"], validate=True)
                        require(
                            chunk["job_id"] == jid
                            and chunk["offset"] == offset
                            and 0 < len(data) <= 12288
                            and chunk["next_offset"] == offset + len(data)
                            and chunk["sha256"] == receipt["export_sha256"]
                            and chunk["total_bytes"] <= 8 * 1024**2,
                            "native_export_integrity",
                        )
                        raw.extend(data)
                        offset += len(data)
                        require(offset <= 8 * 1024**2, "native_export_limit")
                        if chunk["eof"]:
                            require(
                                offset == chunk["total_bytes"]
                                and hashlib.sha256(raw).hexdigest() == receipt["export_sha256"],
                                "native_export_integrity",
                            )
                            break
                    from native_llm_bench.contracts import decode

                    path = self.ledger.root / (jid + ".export.json")
                    if path.exists():
                        require(path.read_bytes() == raw, "native_export_changed")
                    else:
                        storage.write(path, decode(raw))
                    item["export_sha256"] = receipt["export_sha256"]
                saved.append(item)
            with self.ledger.transaction() as db:
                self.ledger.append(
                    db,
                    "native-runner",
                    "FINISH",
                    {
                        "operation_id": approval["operation_id"],
                        "lease_id": lease["lease_id"],
                        "outcome": args["outcome"],
                        "report": args["report"],
                        "jobs": saved,
                    },
                )
        return self.reconcile_finish()

    def reconcile_finish(self):
        # Also called by the existing service after restart. No experiment selection.
        with self.ledger.transaction() as db:
            events = self.ledger.read(db, "native-runner")
        finished = [e["body"] for e in events if e["kind"] == "FINISH"]
        if not finished:
            return None
        finish = finished[-1]
        if any(
            e["kind"] == "STOPPED" and e["body"]["lease_id"] == finish["lease_id"] for e in events
        ):
            return {"verified_stopped": True, "status": "RELEASED"}
        lease = self.access.lease.read()
        require(lease and lease["lease_id"] == finish["lease_id"], "finish_lease_changed")
        result = self.access.call("vm_stop", {}, expected_lease=finish["lease_id"])
        if result["verified_stopped"]:
            with self.ledger.transaction() as db:
                self.ledger.append(
                    db,
                    "native-runner",
                    "STOPPED",
                    {
                        "lease_id": finish["lease_id"],
                        "operation_id": finish["operation_id"],
                        "verified_at": self.clock(),
                    },
                )
        return result


def storage_path_sha(path):
    from native_llm_bench.contracts import sha256_file

    return sha256_file(path)
