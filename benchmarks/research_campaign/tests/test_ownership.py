"""Fake-GCP qualification of the production ownership algorithm, no cloud calls."""

import json
from contextlib import nullcontext
from types import SimpleNamespace

import pytest
from conftest import queue, register
from native_llm_bench.contracts import InvalidArtifact

from jewelai_research.leases import LeaseJournal
from jewelai_research.lifecycle import GcpLab
from jewelai_research.worker import Worker


class Cloud:
    def __init__(self, status="TERMINATED"):
        self.d = {
            "id": "987",
            "name": "jewelai-llm-lab",
            "status": status,
            "lastStartTimestamp": "2026-11-12T01:00:00Z",
            "machineType": "zones/b/e2-medium",
            "networkInterfaces": [{}],
        }
        self.calls, self.after_start, self.fail_describe = [], None, False
        self.after_describe = None

    def __call__(self, args, **kwargs):
        assert "shell" not in kwargs
        assert "--project=mmjewellai-preprod" in args and "--zone=europe-west1-b" in args
        self.calls.append(args)
        if args[2] == "operations":
            data = {
                "name": "operation-owned",
                "operationType": "start",
                "status": "DONE",
                "targetId": "987",
                "targetLink": "https://compute.invalid/projects/mmjewellai-preprod/zones/europe-west1-b/instances/jewelai-llm-lab",
                "startTime": "2026-11-12T02:00:00Z",
                "endTime": "2026-11-12T02:00:02Z",
            }
        elif args[3] == "describe":
            if self.fail_describe:
                raise RuntimeError("sensitive_cloud_error")
            data = self.d
            if self.after_describe:
                callback, self.after_describe = self.after_describe, None
                callback()
        elif args[3] == "start":
            assert "--async" in args
            self.d.update(status="RUNNING", lastStartTimestamp="2026-11-12T02:00:01Z")
            if self.after_start:
                self.after_start()
            data = {"name": "operation-owned"}
        elif args[3] == "stop":
            self.d["status"] = "TERMINATED"
            data = {"name": "operation-stop"}
        else:
            pytest.fail("unexpected cloud operation")
        return SimpleNamespace(returncode=0, stdout=json.dumps(data).encode())

    def count(self, command):
        return sum(c[2] == "instances" and c[3] == command for c in self.calls)


def lab(cloud):
    driver = GcpLab(
        "FAKE_GCLOUD",
        activation_permit=True,
        run=cloud,
        sleep=lambda _: None,
        tunnel=SimpleNamespace(open=lambda: None, close=lambda: None),
        exclusive_use=nullcontext,
    )
    # Only the offline composition gate is adapted. Actual ownership/operation logic and
    # fixed argv are the production classes; LIVE envelope activation remains prohibited.
    driver.check_envelope = lambda e: None
    return driver


def state(f):
    with f.c.ledger.connect() as db:
        return f.c.state(db, f.envelope["campaign_id"])


def test_idle_polling_never_stops_preexisting_vm(campaign):
    f, cloud = campaign, Cloud("RUNNING")
    assert Worker(f.c, lab(cloud), f.model).once(f.envelope["campaign_id"]) == "IDLE"
    assert not cloud.calls
    assert state(f)["cleanup"] is None and state(f)["lease"] is None


@pytest.mark.parametrize("failure", ["already_running", "describe_error", "wrong_configuration"])
def test_failed_prestart_never_stops_unowned_vm(campaign, failure):
    f, cloud = campaign, Cloud("RUNNING" if failure == "already_running" else "TERMINATED")
    cloud.fail_describe = failure == "describe_error"
    if failure == "wrong_configuration":
        cloud.d["machineType"] = "zones/b/e2-standard-8"
    register(f)
    queue(f)
    Worker(f.c, lab(cloud), f.model).once(f.envelope["campaign_id"])
    assert cloud.count("start") == 0 and cloud.count("stop") == 0
    assert state(f)["cleanup"]["status"] == "BLOCKED"
    assert state(f)["cleanup"]["verified_stopped"] is False


def test_owned_start_and_stop_have_durable_operation_and_incarnation_proof(campaign):
    f, cloud = campaign, Cloud()
    register(f)
    queue(f)
    Worker(f.c, lab(cloud), f.model).once(f.envelope["campaign_id"])
    s = state(f)
    assert cloud.count("start") == 1 and cloud.count("stop") == 1
    assert s["lease"]["phase"] == "RELEASED" and s["cleanup"]["verified_stopped"]
    assert s["lease"]["fingerprint"] == {"instance_id": "987", "last_start": "2026-11-12T02:00:01Z"}
    assert s["lease"]["operation_proof"]["name"] == "operation-owned"
    # Another task can now start the VM. Polling the completed campaign must not stop it.
    cloud.d.update(status="RUNNING", lastStartTimestamp="2026-11-12T03:00:00Z")
    count = len(cloud.calls)
    Worker(f.c, lab(cloud), f.model).once(f.envelope["campaign_id"])
    assert len(cloud.calls) == count


def test_start_response_lost_is_ambiguous_not_shutdown_authority(campaign):
    f, cloud = campaign, Cloud()
    journal = LeaseJournal(f.c, f.envelope["campaign_id"])
    driver = lab(cloud)

    def lost_response():
        raise SystemExit("simulated process interruption")

    cloud.after_start = lost_response
    with pytest.raises(SystemExit):
        driver.start(f.envelope, journal)
    assert journal.read()["phase"] == "START_INTENT" and cloud.d["status"] == "RUNNING"
    receipt = lab(cloud).stop(LeaseJournal(f.c, f.envelope["campaign_id"]))
    assert receipt["status"] == "BLOCKED" and not receipt["verified_stopped"]
    assert cloud.count("stop") == 0


def test_submitted_start_recovers_exact_operation_before_shutdown(campaign):
    f, cloud = campaign, Cloud()
    journal, driver = LeaseJournal(f.c, f.envelope["campaign_id"]), lab(cloud)

    def interrupt(_):
        raise SystemExit

    driver.adopt = interrupt
    with pytest.raises(SystemExit):
        driver.start(f.envelope, journal)
    assert journal.read()["phase"] == "START_SUBMITTED"
    receipt = lab(cloud).stop(LeaseJournal(f.c, f.envelope["campaign_id"]))
    assert receipt["verified_stopped"] and cloud.count("stop") == 1


@pytest.mark.parametrize("change", [{"id": "999"}, {"lastStartTimestamp": "2026-11-12T04:00:00Z"}])
def test_changed_incarnation_or_start_generation_blocks_shutdown(campaign, change):
    f, cloud = campaign, Cloud()
    journal, driver = LeaseJournal(f.c, f.envelope["campaign_id"]), lab(cloud)
    driver.start(f.envelope, journal)
    cloud.d.update(change)
    receipt = driver.stop(journal)
    assert not receipt["verified_stopped"] and cloud.count("stop") == 0


def test_stop_during_start_still_acquires_proof_before_own_cleanup(campaign):
    f, cloud = campaign, Cloud()
    register(f)
    queue(f)
    cloud.after_start = lambda: f.c.call(
        f.principal,
        "stop_campaign",
        {
            "campaign_id": f.envelope["campaign_id"],
            "idempotency_key": "during-start",
            "reason": "emergency",
        },
    )
    assert Worker(f.c, lab(cloud), f.model).once(f.envelope["campaign_id"]) == "STOPPED"
    assert cloud.count("start") == 1 and cloud.count("stop") == 1 and not f.model.calls
    assert state(f)["cleanup"]["verified_stopped"]


def test_unscoped_stop_requires_durable_lease_without_cloud_access():
    cloud, driver = Cloud("RUNNING"), None
    driver = lab(cloud)
    with pytest.raises(InvalidArtifact, match="durable_lease_required"):
        driver.stop()
    assert not cloud.calls


def test_unqualified_exclusive_use_guard_prevents_cloud_mutation(campaign):
    cloud = Cloud()
    driver = GcpLab("FAKE_GCLOUD", activation_permit=True, run=cloud)
    driver.check_envelope = lambda e: None
    with pytest.raises(InvalidArtifact, match="exclusive_vm_use_not_qualified"):
        driver.start(campaign.envelope, LeaseJournal(campaign.c, campaign.envelope["campaign_id"]))
    with pytest.raises(InvalidArtifact, match="exclusive_vm_use_not_qualified"):
        driver._command("stop")
    assert not cloud.calls


def test_stop_before_start_rpc_never_starts_or_stops_vm(campaign):
    f, cloud = campaign, Cloud()
    register(f)
    queue(f)
    cloud.after_describe = lambda: f.c.call(
        f.principal,
        "stop_campaign",
        {
            "campaign_id": f.envelope["campaign_id"],
            "idempotency_key": "pre-start-stop",
            "reason": "cancel before RPC",
        },
    )
    assert Worker(f.c, lab(cloud), f.model).once(f.envelope["campaign_id"]) == "STOPPED"
    assert cloud.count("start") == 0 and cloud.count("stop") == 0
    assert not state(f)["cleanup"]["verified_stopped"]


def test_worker_shutdown_signal_checks_start_boundary_before_paid_rpc(campaign):
    import threading

    f, cloud = campaign, Cloud()
    register(f)
    queue(f)
    stop = threading.Event()
    cloud.after_describe = stop.set
    worker = Worker(f.c, lab(cloud), f.model)
    worker.serve(f.envelope["campaign_id"], poll_seconds=0, stop=stop)
    assert cloud.count("start") == 0 and cloud.count("stop") == 0 and not f.model.calls


def test_old_cleanup_receipt_cannot_finalize_a_new_owned_lease(campaign):
    f, cid = campaign, campaign.envelope["campaign_id"]
    register(f)
    queue(f)
    f.worker.once(cid)
    old_cleanup = state(f)["cleanup"]
    journal = LeaseJournal(f.c, cid)
    f.lab.start(f.envelope, journal)
    assert state(f)["cleanup"]["verified_stopped"] is False
    # Reproduce an old receipt arriving while a later lease owns the instance.
    with f.c.ledger.transaction() as db:
        f.c.ledger.append(db, cid, "CLEANUP", old_cleanup)
    with pytest.raises(InvalidArtifact, match="cleanup_not_verified"):
        f.c.call(
            f.principal,
            "finalize_campaign",
            {
                "campaign_id": cid,
                "idempotency_key": "f",
                "conclusion": "must not certify stale cleanup",
            },
        )
    assert f.worker._cleanup(cid) is True
    assert (
        f.c.call(
            f.principal,
            "finalize_campaign",
            {
                "campaign_id": cid,
                "idempotency_key": "f",
                "conclusion": "must not certify stale cleanup",
            },
        )["report"]["lifecycle_lease"]["phase"]
        == "RELEASED"
    )
