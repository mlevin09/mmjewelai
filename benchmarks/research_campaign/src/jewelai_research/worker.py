"""Restartable single worker. Unknown attempts retain their entire reservation, never retry."""

import fcntl
import os
import time
from dataclasses import replace

from native_llm_bench import storage
from native_llm_bench.contracts import digest, load, require, sha256_file
from native_llm_bench.instructions import system_instruction
from native_llm_bench.runner import _validate_result, execute

from .contracts import experiment_plan, experiment_runtime
from .controller import TERMINAL
from .leases import LeaseJournal, StartCancelled


class CampaignStopped(RuntimeError):
    pass


class Worker:
    def __init__(self, controller, lifecycle, transport, *, delivery=None):
        self.c = controller
        self.lifecycle = lifecycle
        self.transport = transport
        self.delivery = delivery
        self.cancellation = lambda: False

    def _event(self, cid, kind, body):
        with self.c.ledger.transaction() as db:
            self.c.ledger.append(db, cid, kind, body)

    def _cleanup(self, cid):
        # Cleanup runs even if source validation or the runner failed. Exceptions are bounded.
        journal = LeaseJournal(self.c, cid)
        try:
            receipt = self.lifecycle.stop(journal)
        except Exception:
            receipt = journal.blocked("ownership_or_shutdown_verification_failed")
        self._event(cid, "CLEANUP", {**receipt, "at": self.c.clock()})
        return receipt["verified_stopped"]

    def once(self, cid):
        fd = os.open(self.c.ledger.root / ".worker.lock", os.O_CREAT | os.O_RDWR, 0o600)
        try:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                require(False, "worker_already_active")
            return self._once(cid)
        finally:
            os.close(fd)

    def _once(self, cid):
        with self.c.ledger.transaction() as db:
            state = self.c.state(db, cid)
            if state["report"]:
                finalized = True
            else:
                finalized = False
            # An interrupted worker may have issued requests. Do not resume/retry inference.
            running = [x for x in state["experiments"].values() if x["status"] == "RUNNING"]
            expired = not finalized and self.c.clock() >= self.c.limits(state)["deadline"]
            stopped = state["stopped"] or expired
            if expired and not state["stopped"]:
                self.c.ledger.append(db, cid, "STOP", {"reason": "deadline", "at": self.c.clock()})
            queued = [x for x in state["experiments"].values() if x["status"] == "QUEUED"]
        if finalized:
            if self.delivery is not None:
                try:
                    self.delivery.deliver(self.c, cid)
                except Exception:
                    self._event(
                        cid, "DELIVERY_BLOCKED", {"reason": "private_delivery_not_verified"}
                    )
                    return "DELIVERY_BLOCKED"
            return "FINALIZED"
        if running:
            try:
                for x in running:
                    self._finish(cid, x, "UNKNOWN", "interrupted_worker_no_automatic_retry")
            finally:
                self._cleanup(cid)
            return "RECOVERED_UNKNOWN"
        if stopped:
            unfinished = [x for x in state["experiments"].values() if x["status"] not in TERMINAL]
            try:
                for x in unfinished:
                    self._finish(cid, x, "STOPPED", "campaign_stop")
            finally:
                if (
                    unfinished
                    or state["cleanup"] is None
                    or (
                        state["lease"]
                        and state["lease"]["phase"] in {"START_SUBMITTED", "OWNED", "STOP_INTENT"}
                    )
                ):
                    self._cleanup(cid)
            return "STOPPED"
        if not queued:
            # Only reconcile an actual unfinished lease. Idle polling is NEVER stop authority.
            if state["lease"] and state["lease"]["phase"] not in {
                "RELEASED",
                "NO_START",
                "BLOCKED",
            }:
                self._cleanup(cid)
            return "IDLE"
        x = queued[0]
        run_dir = None
        status, reason = "FAILED", "execution_failed"
        try:
            self.c.inputs.verify(state["envelope"])
            config, override, plan = experiment_plan(
                state["envelope"],
                self.c.inputs,
                x["profile"],
                x["sessions"],
                x.get("parameters", {}),
            )
            corpus, _ = experiment_runtime(
                self.c.inputs, x["profile"], x.get("parameters", {}), x["sessions"]
            )
            require(digest(plan) == x["plan_sha256"], "registered_plan_changed")
            run_dir, _ = storage.create(self.c.directory(cid) / "runs", plan)
            # Durable claim and run identity BEFORE VM start / inference, under same DB lock
            # used by stop_campaign. An emergency stop cannot be lost to a stale snapshot.
            with self.c.ledger.transaction() as db:
                latest = self.c.state(db, cid)
                self.c.live_window(latest)
                require(
                    latest["experiments"][x["experiment_id"]]["status"] == "QUEUED",
                    "claim_state_changed",
                )
                self.c.ledger.append(
                    db,
                    cid,
                    "RUNNING",
                    {
                        "experiment_id": x["experiment_id"],
                        "status": "RUNNING",
                        "run_id": run_dir.name,
                        "at": self.c.clock(),
                    },
                )
            self.lifecycle.start(
                state["envelope"], LeaseJournal(self.c, cid, cancellation=self.cancellation)
            )
            require(self.lifecycle.status() == "RUNNING", "vm_not_running")
            attempts = 0

            def metered(cfg, payload):
                nonlocal attempts
                if self.cancellation():
                    raise CampaignStopped
                with self.c.ledger.transaction() as db:
                    current = self.c.state(db, cid)
                    try:
                        self.c.live_window(current)
                    except ValueError as exc:
                        raise CampaignStopped from exc
                    remaining = self.c.limits(current)["deadline"] - self.c.clock()
                    require(attempts < x["reserved_attempts"], "attempt_reservation_exceeded")
                    attempts += 1
                    # Pre-I/O attempt receipt; unknown/timeout costs never refunded.
                    self.c.ledger.append(
                        db,
                        cid,
                        "ATTEMPT",
                        {
                            "experiment_id": x["experiment_id"],
                            "number": attempts,
                            "request_sha256": digest(payload),
                            "at": self.c.clock(),
                        },
                    )
                self.c.inputs.verify(state["envelope"])
                return self.transport(
                    replace(cfg, timeout_seconds=min(cfg.timeout_seconds, max(0.01, remaining))),
                    payload,
                )

            summary = execute(
                corpus,
                config,
                self.c.inputs.manifest,
                None,
                seed=state["envelope"]["scheduling_seed"],
                selected=x["sessions"],
                exclude_holdouts=True,
                resume=run_dir,
                retry_uncertain=False,
                instruction_override=override,
                transport=metered,
            )
            status, reason = summary["status"], "runner_terminal"
        except (CampaignStopped, StartCancelled):
            status, reason = "STOPPED", "campaign_stop_or_deadline"
        except Exception:
            # Raw exception strings/bodies/credentials never become tool errors or ledger fields.
            status, reason = "UNKNOWN", "execution_failed_outcome_unknown"
        except BaseException:
            status, reason = "UNKNOWN", "worker_interrupted"
            raise
        finally:
            # If killed after runner completed but before this event, recovery conservatively
            # records UNKNOWN; original runner files remain available for independent review.
            try:
                self._finish(
                    cid, {**x, **({"run_id": run_dir.name} if run_dir else {})}, status, reason
                )
            finally:
                self._cleanup(cid)
        return status

    def _finish(self, cid, x, status, reason):
        receipt = {
            "experiment_id": x["experiment_id"],
            "status": status,
            "reason": reason,
            "reserved_attempts_charged": x["reserved_attempts"],
            "at": self.c.clock(),
        }
        if x.get("run_id"):
            directory = self.c.directory(cid) / "runs" / x["run_id"]
            exported = storage.export(directory)
            run = exported["run"]
            require(run["plan_sha256"] == x["plan_sha256"], "run_plan_mismatch")
            self._verify_history(cid, x, run, directory)
            receipt["runner"] = exported
            receipt["measurements"] = self._measure(exported)
        path = self.c.directory(cid) / (x["experiment_id"] + ".receipt.json")
        if path.exists():
            # Crash after immutable receipt, before result event: preserve the receipt verbatim.
            prior = load(path)
            require(prior["experiment_id"] == x["experiment_id"], "receipt_scope")
            require(
                prior.get("runner") == receipt.get("runner")
                and prior["reserved_attempts_charged"] == x["reserved_attempts"],
                "recovery_receipt_mismatch",
            )
            status, receipt = prior["status"], prior
        else:
            storage.write(path, receipt)
        self._event(
            cid,
            "RESULT",
            {
                "experiment_id": x["experiment_id"],
                "status": status,
                "receipt_sha256": sha256_file(path),
                "reason": receipt["reason"],
                "measurements": receipt.get("measurements"),
                **({"run_id": x["run_id"]} if x.get("run_id") else {}),
            },
        )

    def _verify_history(self, cid, x, run, directory):
        with self.c.ledger.connect() as db:
            envelope = self.c.state(db, cid)["envelope"]
        parameters = x.get("parameters", {})
        config, _, expected = experiment_plan(
            envelope, self.c.inputs, x["profile"], x["sessions"], parameters
        )
        corpus, _ = experiment_runtime(self.c.inputs, x["profile"], parameters, x["sessions"])
        require(run["plan"] == expected, "runner_plan_integrity")
        require(
            run["runner"]["source_sha256"] == self.c.inputs.runner_sha, "runner_identity_integrity"
        )
        sessions = {s["session_id"]: s for s in corpus["sessions"]}
        for sid in expected["session_order"]:
            session = sessions[sid]
            system, _ = system_instruction(corpus, session, expected)
            history = [{"role": "system", "content": system}]
            failed = False
            for turn in session["turns"]:
                require(
                    storage.attempts(directory, sid, turn["turn_id"]) <= 1,
                    "unexpected_runner_retry",
                )
                req, res = storage.files(directory, sid, turn["turn_id"], 1)
                if not req.exists():
                    failed = True
                    continue
                require(not failed, "request_after_missing_or_failed_history")
                request = load(req)
                history.append({"role": "user", "content": turn["text"]})
                require(request["payload"] == config.payload(history), "request_history_integrity")
                if not res.exists():
                    failed = True
                    continue
                result = load(res)
                _validate_result(request, result)
                if result["status"] == "COMPLETED":
                    history.append(result["assistant_message"])
                else:
                    failed = True

    @staticmethod
    def _measure(exported):
        records = exported["attempt_results"]
        counts = {}
        for r in records:
            counts[r["status"]] = counts.get(r["status"], 0) + 1
        return {
            "attempts_with_results": len(records),
            "attempts_recorded": len(exported["requests"]),
            "outcome_unknown": len(exported["requests"]) - len(records),
            "planned_turns": sum(len(ts) for ts in exported["run"]["plan"]["turn_order"].values()),
            "statuses": counts,
            "completed": counts.get("COMPLETED", 0),
            "truncated": counts.get("TRUNCATED", 0),
            "observed_wall_seconds": sum(r["wall_seconds"] or 0 for r in records),
            "professional_quality": "NOT_SCORED_REVIEW_REQUIRED",
        }

    def serve(self, cid, *, poll_seconds=1, stop=None):
        """Supervisor entrypoint. Durable queue survives Workspace and worker interruptions."""
        # Each once() owns cleanup under the global worker lock, including BaseException.
        # Never stop the VM outside that lock while another worker may own it.
        self.cancellation = stop.is_set if stop is not None else lambda: False
        while not self.cancellation():
            status = self.once(cid)
            if status in ("FINALIZED", "DELIVERY_BLOCKED"):
                return
            time.sleep(poll_seconds)
