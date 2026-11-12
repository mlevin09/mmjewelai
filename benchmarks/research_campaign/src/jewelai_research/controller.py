"""Seven campaign tools. Registration and queueing are atomic; inference is outside SQL."""

import copy
import time

from native_llm_bench import storage
from native_llm_bench.contracts import canonical, digest, keys, load, require, sha256_file

from .contracts import (
    PROFILES,
    VERSION,
    bounded_text,
    experiment_plan,
    identifier,
    validate_envelope,
)
from .ledger import Ledger, projection

TERMINAL = {"COMPLETED", "INCOMPLETE", "UNKNOWN", "FAILED", "STOPPED"}
TOOLS = (
    "campaign_status",
    "propose_and_register_experiment",
    "execute_registered_experiment",
    "get_experiment_results",
    "list_ledger",
    "finalize_campaign",
    "stop_campaign",
)
READ = {"campaign_status", "get_experiment_results", "list_ledger"}


class Controller:
    def __init__(self, root, inputs, *, clock=time.time):
        self.ledger = Ledger(root)
        self.inputs = inputs
        self.clock = clock

    def activate(self, envelope):
        """Local operator entrypoint, deliberately absent from MCP tools."""
        e = validate_envelope(envelope, self.inputs)
        require(e["period_start"] <= self.clock() < e["period_end"], "outside_activation_period")
        with self.ledger.transaction() as db:
            require(not self.ledger.read(db, e["campaign_id"]), "campaign_exists")
            self.ledger.append(
                db,
                e["campaign_id"],
                "ACTIVATED",
                {"envelope": e, "envelope_sha256": digest(e), "at": self.clock()},
            )
        return {"campaign_id": e["campaign_id"], "envelope_sha256": digest(e), "mode": e["mode"]}

    def state(self, db, cid):
        return projection(self.ledger.read(db, cid))

    def directory(self, cid):
        return self.ledger.root / identifier(cid)

    def limits(self, state):
        e = state["envelope"]
        experiments = list(state["experiments"].values())
        budget = e["budget"]
        reserve = sum(budget[x] for x in ("lifecycle_reserve", "disk_reserve", "agent_reserve"))
        attempted = sum(x["reserved_attempts"] for x in experiments)
        charged = reserve + attempted * budget["attempt_cost"]
        return {
            "reserved_proxy_cost": charged,
            "hard_ceiling": budget["hard_ceiling"],
            "soft_limit_reached": charged >= budget["soft_limit"],
            "reserved_attempts": attempted,
            "reserved_turns": sum(x["turns"] for x in experiments),
            "experiments": len(experiments),
            "deadline": min(e["period_end"], state["created_at"] + e["max_wall_seconds"]),
            "cost_semantics": "worst_case_reservation_never_refunded_NOT_actual_GCP_billing",
        }

    def live_window(self, state):
        require(not state["stopped"] and not state["report"], "campaign_closed")
        e = state["envelope"]
        require(
            e["period_start"] <= self.clock() < self.limits(state)["deadline"], "campaign_deadline"
        )
        self.inputs.verify(e)

    def call(self, principal, name, args):
        require(name in TOOLS, "unknown_tool")
        require(isinstance(args, dict), "invalid_arguments")
        cid = identifier(args.get("campaign_id"))
        with self.ledger.transaction() as db:
            state = self.state(db, cid)
            require(principal.subject == state["envelope"]["subject"], "campaign_forbidden")
            require(
                ("campaign.read" if name in READ else "campaign.execute") in principal.scopes,
                "insufficient_scope",
            )
            fields = {"campaign_id"}
            fields |= {
                "propose_and_register_experiment": {
                    "idempotency_key",
                    "experiment_id",
                    "profile",
                    "sessions",
                    "hypothesis",
                },
                "execute_registered_experiment": {"idempotency_key", "experiment_id"},
                "get_experiment_results": {"experiment_id"},
                "list_ledger": {"offset", "limit"},
                "finalize_campaign": {"idempotency_key", "conclusion"},
                "stop_campaign": {"idempotency_key", "reason"},
            }.get(name, set())
            if name == "propose_and_register_experiment" and "parameters" in args:
                fields |= {"parameters"}
                require(isinstance(args["parameters"], dict), "invalid_treatment")
            keys(args, fields)
            if name in READ:
                return self._read(db, cid, state, name, args)
            key = identifier(args["idempotency_key"])
            prior = state["calls"].get(key)
            fingerprint = digest({"tool": name, "arguments": args})
            if prior:
                require(prior["fingerprint"] == fingerprint, "idempotency_conflict")
                return prior["result"]
            result = self._write(db, cid, state, name, args)
            self.ledger.append(
                db, cid, "CALL", {"key": key, "fingerprint": fingerprint, "result": result}
            )
            return result

    def _read(self, db, cid, state, name, args):
        if name == "campaign_status":
            return {
                "version": VERSION,
                "campaign_id": cid,
                "mode": state["envelope"]["mode"],
                "stopped": state["stopped"],
                "finalized": bool(state["report"]),
                "cleanup": state["cleanup"],
                "limits": self.limits(state),
                "profiles": {
                    p: {
                        **PROFILES,
                        **(self.inputs.policy["profiles"] if self.inputs.policy else {}),
                    }[p]
                    for p in state["envelope"]["allowed_profiles"]
                },
                "experiment_policy": self.inputs.policy,
                "lease": state["lease"],
                "report_delivery": (
                    {
                        **(state["delivery"] or {}),
                        "status": "BLOCKED",
                        "failure": state["delivery_failure"],
                    }
                    if state["delivery_failure"]
                    else state["delivery"]
                ),
                "sample_ids": state["envelope"]["allowed_sessions"],
                "experiments": [
                    {k: x[k] for k in ("experiment_id", "profile", "status")}
                    for x in state["experiments"].values()
                ],
            }
        if name == "list_ledger":
            offset, limit = args["offset"], args["limit"]
            require(
                type(offset) is int and offset >= 0 and type(limit) is int and 1 <= limit <= 100,
                "invalid_page",
            )
            events = self.ledger.read(db, cid)
            return {"events": events[offset : offset + limit], "total": len(events)}
        x = self._experiment(state, args["experiment_id"])
        result = copy.deepcopy(x)
        if "receipt_sha256" in x:
            path = self.directory(cid) / (x["experiment_id"] + ".receipt.json")
            require(sha256_file(path) == x["receipt_sha256"], "receipt_integrity")
            result["receipt"] = load(path)
            if "runner" in result["receipt"]:
                original = storage.export(self.directory(cid) / "runs" / x["run_id"])
                require(original == result["receipt"]["runner"], "raw_journal_changed")
        return result

    @staticmethod
    def _experiment(state, eid):
        identifier(eid)
        require(eid in state["experiments"], "unknown_experiment")
        return state["experiments"][eid]

    def _write(self, db, cid, state, name, args):
        if name == "stop_campaign":
            bounded_text(args["reason"], 500)
            self.ledger.append(db, cid, "STOP", {"reason": args["reason"], "at": self.clock()})
            return {
                "stop_requested": True,
                "cleanup_verified": False,
                "instruction": "worker must verify shutdown; status is authoritative",
            }
        if name == "finalize_campaign":
            return self._finalize(db, cid, state, args["conclusion"])
        self.live_window(state)
        if name == "execute_registered_experiment":
            x = self._experiment(state, args["experiment_id"])
            require(x["status"] == "REGISTERED", "experiment_not_registered")
            self.ledger.append(
                db,
                cid,
                "QUEUED",
                {"experiment_id": x["experiment_id"], "status": "QUEUED", "at": self.clock()},
            )
            return {"experiment_id": x["experiment_id"], "status": "QUEUED"}
        eid = identifier(args["experiment_id"])
        require(eid not in state["experiments"], "experiment_exists")
        h = args["hypothesis"]
        keys(
            h,
            (
                "statement",
                "alternatives",
                "primary_variable",
                "falsification",
                "rationale",
                "evidence_experiments",
            ),
        )
        for k in ("statement", "primary_variable", "falsification", "rationale"):
            bounded_text(h[k])
        require(
            isinstance(h["alternatives"], list) and 1 <= len(h["alternatives"]) <= 5,
            "missing_competing_hypotheses",
        )
        for a in h["alternatives"]:
            bounded_text(a)
        require(isinstance(h["evidence_experiments"], list), "invalid_evidence")
        for earlier in h["evidence_experiments"]:
            require(self._experiment(state, earlier)["status"] in TERMINAL, "evidence_not_ready")
        _, _, plan = experiment_plan(
            state["envelope"],
            self.inputs,
            args["profile"],
            args["sessions"],
            args.get("parameters", {}),
        )
        turns = sum(len(ts) for ts in plan["turn_order"].values())
        limits, e = self.limits(state), state["envelope"]
        require(
            limits["experiments"] + 1 <= e["max_experiments"]
            and limits["reserved_turns"] + turns <= e["max_turns"]
            and limits["reserved_attempts"] + turns <= e["max_attempts"]
            and limits["reserved_proxy_cost"] + turns * e["budget"]["attempt_cost"]
            <= e["budget"]["hard_ceiling"],
            "campaign_budget_exhausted",
        )
        record = {
            "experiment_id": eid,
            "profile": args["profile"],
            "parameters": args.get("parameters", {}),
            "operator_policy_sha256": digest(self.inputs.policy),
            "base_runtime_sha256": digest(self.inputs.corpus),
            "effective_runtime_sha256": plan["runtime_artifact_sha256"],
            "measurement_condition": {
                "max_tokens": plan["configuration"]["max_tokens"],
                "historical_A_B_D_equivalence": "NOT_ESTABLISHED; historical max_tokens=256",
            },
            "sessions": args["sessions"],
            "hypothesis": h,
            "plan_sha256": digest(plan),
            "turns": turns,
            "reserved_attempts": turns,
            "at": self.clock(),
        }
        self.ledger.append(db, cid, "REGISTERED", record)
        return {**record, "status": "REGISTERED"}

    def _finalize(self, db, cid, state, conclusion):
        bounded_text(conclusion)
        self.inputs.verify(state["envelope"])
        require(state["report"] is None, "already_finalized")
        require(
            all(x["status"] in TERMINAL for x in state["experiments"].values()),
            "experiments_not_terminal",
        )
        require(
            state["cleanup"]
            and state["cleanup"]["verified_stopped"]
            and state["lease"]
            and state["lease"]["phase"] == "RELEASED"
            and state["cleanup"].get("lease_id") == state["lease"]["lease_id"],
            "cleanup_not_verified",
        )
        report = {
            "version": VERSION,
            "campaign_id": cid,
            "mode": state["envelope"]["mode"],
            "assignment": state["envelope"]["assignment"],
            "envelope_sha256": digest(state["envelope"]),
            "pins": state["envelope"]["pins"],
            "limits": self.limits(state),
            "cleanup": state["cleanup"],
            "lifecycle_lease": state["lease"],
            "experiments": list(state["experiments"].values()),
            "verified_receipts": [
                self._read(
                    db, cid, state, "get_experiment_results", {"experiment_id": x["experiment_id"]}
                )["receipt"]
                for x in state["experiments"].values()
            ],
            "agent_conclusion_UNVERIFIED": conclusion,
            "professional_gold_status": "REVIEW_REQUIRED; no certified winner",
            "limitations": [
                "proxy reservations are not billed-dollar guarantees",
                "Workspace autonomous continuation requires connected validation",
                "synthetic results do not measure Qwen or professional accuracy",
            ],
            "evidence_head": self.ledger.read(db, cid)[-1]["sha256"],
        }
        path = self.directory(cid) / "report.json"
        if path.exists():  # Recover a crash after fsync but before the SQL commit.
            require(load(path) == report, "report_already_exists_with_different_content")
        else:
            storage.write(path, report)
        receipt = {"report_sha256": sha256_file(path), "report": report}
        self.ledger.append(db, cid, "FINALIZED", receipt)
        return receipt

    def verify_report(self, cid):
        with self.ledger.transaction() as db:
            report = self.state(db, cid)["report"]
            require(report is not None, "not_finalized")
            require(
                sha256_file(self.directory(cid) / "report.json") == report["report_sha256"],
                "report_integrity",
            )
            return canonical(report["report"])
