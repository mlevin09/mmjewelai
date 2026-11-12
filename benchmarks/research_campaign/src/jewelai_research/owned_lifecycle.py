"""Start-operation-backed ownership. An ambiguous start is BLOCKED, never permission to stop."""

from datetime import datetime

from native_llm_bench.contracts import require

from .contracts import TARGET
from .leases import LeaseJournal, StartCancelled


def instant(value):
    require(isinstance(value, str), "missing_cloud_timestamp")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    require(parsed.tzinfo is not None, "invalid_cloud_timestamp")
    return parsed


def fingerprint(instance):
    require(isinstance(instance.get("id"), str) and instance["id"].isdigit(), "missing_instance_id")
    instant(instance.get("lastStartTimestamp"))
    return {"instance_id": instance["id"], "last_start": instance["lastStartTimestamp"]}


class OwnedLifecycle:
    """Drivers implement inspect/request_start/operation/request_stop; no unscoped stop API."""

    def start(self, envelope, journal):
        require(isinstance(journal, LeaseJournal), "durable_lease_required")
        self.check_envelope(envelope)
        lease = journal.begin(envelope)
        d = self.inspect()
        if d.get("status") != "TERMINATED":
            journal.blocked("preexisting_vm_not_owned")
            require(False, "preexisting_vm_not_owned")
        self.check_instance(d)
        require(isinstance(d.get("id"), str) and d["id"].isdigit(), "missing_instance_id")
        journal.record(lease["lease_id"], "START_INTENT", instance_id=d["id"])
        if journal.cancelled():
            journal.record(lease["lease_id"], "NO_START", reason="cancelled_before_start_rpc")
            raise StartCancelled
        # If the process dies after RPC but before recording operation identity, ownership
        # is intentionally unprovable. Never adopt a RUNNING VM based on status/time alone.
        operation = self.request_start()
        require(isinstance(operation, dict) and operation.get("name"), "missing_start_operation")
        journal.record(lease["lease_id"], "START_SUBMITTED", operation_name=operation["name"])
        self.adopt(journal)
        if journal.cancelled():
            raise StartCancelled
        self.open()

    def adopt(self, journal):
        lease = journal.read()
        require(lease and lease["phase"] == "START_SUBMITTED", "no_submitted_start")
        for _ in range(12):
            op = self.operation(lease["operation_name"])
            link = "/projects/{project}/zones/{zone}/instances/{vm}".format(**TARGET)
            require(
                op.get("name") == lease["operation_name"]
                and op.get("operationType") == "start"
                and op.get("targetId") == lease["instance_id"]
                and isinstance(op.get("targetLink"), str)
                and op["targetLink"].endswith(link)
                and not op.get("error")
                and not op.get("httpErrorStatusCode"),
                "start_operation_not_owned",
            )
            if op.get("status") == "DONE":
                d = self.inspect()
                identity = fingerprint(d)
                require(
                    d["status"] == "RUNNING"
                    and identity["instance_id"] == lease["instance_id"]
                    and instant(op["startTime"])
                    <= instant(identity["last_start"])
                    <= instant(op["endTime"]),
                    "start_incarnation_not_owned",
                )
                journal.record(
                    lease["lease_id"],
                    "OWNED",
                    fingerprint=identity,
                    operation_proof={
                        k: op[k] for k in ("name", "targetId", "targetLink", "startTime", "endTime")
                    },
                )
                return
            self.sleep(5)
        require(False, "start_operation_not_terminal")

    def stop(self, journal=None):
        require(isinstance(journal, LeaseJournal), "durable_lease_required")
        lease = journal.read()
        if not lease:
            return journal.blocked("ownership_not_acquired")
        if lease["phase"] == "RELEASED":
            return {
                "verified_stopped": True,
                "status": "RELEASED",
                "lease_id": lease["lease_id"],
                "verified_at": lease["at"],
            }  # historical proof, no action on current VM
        try:
            if lease["phase"] == "START_SUBMITTED":
                self.adopt(journal)
                lease = journal.read()
            if lease["phase"] not in {"OWNED", "STOP_INTENT"}:
                return journal.blocked("ownership_not_proven")
            # Exact VM incarnation AND exact start generation must still match. A restart
            # by another operator invalidates our ownership even if name/id stayed equal.
            d = self.inspect()
            require(fingerprint(d) == lease["fingerprint"], "vm_ownership_changed")
            if d["status"] != "TERMINATED":
                require(d["status"] == "RUNNING", "owned_vm_not_stoppable")
                journal.record(lease["lease_id"], "STOP_INTENT")
                self.request_stop()
            for _ in range(12):
                d = self.inspect()
                require(fingerprint(d) == lease["fingerprint"], "vm_ownership_changed")
                if d["status"] == "TERMINATED":
                    journal.record(lease["lease_id"], "RELEASED")
                    return {
                        "verified_stopped": True,
                        "status": "RELEASED",
                        "lease_id": lease["lease_id"],
                    }
                self.sleep(5)
            return journal.blocked("owned_shutdown_not_verified")
        except Exception:
            return journal.blocked("ownership_or_shutdown_verification_failed")
        finally:
            self.close()  # closes only this driver's own local tunnel process

    def open(self):
        pass

    def close(self):
        pass

    def status(self):
        return self.inspect()["status"]
