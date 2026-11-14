import copy
import hashlib

import pytest
from conftest import queue, register
from native_llm_bench.contracts import InvalidArtifact, digest

from jewelai_research.delivery import BENCHMARK_FOLDER, ReportDelivery
from jewelai_research.worker import Worker


class PrivateDrive:
    def __init__(self):
        self.files = {
            BENCHMARK_FOLDER: {
                "id": BENCHMARK_FOLDER,
                "mimeType": "application/vnd.google-apps.folder",
                "permissions": [{"id": "approved-owner", "type": "user"}],
                "capabilities": {"canAddChildren": True},
            }
        }
        self.allocations, self.creates, self.payload = 0, 0, None
        self.interrupt_after_upload = False

    def metadata(self, file_id):
        return copy.deepcopy(self.files.get(file_id))

    def allocate(self):
        self.allocations += 1
        return "synthetic-private-report"

    def create(self, file_id, folder, payload, sha):
        self.creates += 1
        self.payload = payload
        self.files[file_id] = {
            "id": file_id,
            "parents": [folder],
            "appProperties": {"jewelaiReportSha256": sha},
            "permissions": [{"id": "approved-owner", "type": "user"}],
        }
        if self.interrupt_after_upload:
            raise OSError("private upstream body not allowed in receipts")

    def download(self, file_id, maximum):
        assert file_id == "synthetic-private-report" and len(self.payload) <= maximum
        return self.payload


@pytest.fixture
def finished(campaign):
    f, cid = campaign, campaign.envelope["campaign_id"]
    register(f)
    queue(f)
    f.worker.once(cid)
    f.c.call(
        f.principal,
        "finalize_campaign",
        {"campaign_id": cid, "idempotency_key": "final", "conclusion": "Synthetic research only."},
    )
    config = {
        "enabled": True,
        "campaign_id": cid,
        "envelope_sha256": digest(f.envelope),
        "folder_id": BENCHMARK_FOLDER,
        "maximum_bytes": 200000,
        "approved_permission_ids": ["approved-owner"],
    }
    return f, config, PrivateDrive()


def test_finalized_report_delivered_once_by_independent_worker_and_readback_verified(finished):
    f, cfg, drive = finished
    delivery = ReportDelivery(cfg, drive)
    worker = Worker(f.c, f.lab, f.model, delivery=delivery)
    assert worker.once(cfg["campaign_id"]) == "FINALIZED"
    assert worker.once(cfg["campaign_id"]) == "FINALIZED"
    assert drive.allocations == 1 and drive.creates == 1
    original = (f.c.directory(cfg["campaign_id"]) / "report.json").read_bytes()
    assert drive.payload == original
    state = f.c.call(f.principal, "campaign_status", {"campaign_id": cfg["campaign_id"]})
    assert state["report_delivery"]["status"] == "DELIVERED"
    assert state["report_delivery"]["sha256"] == hashlib.sha256(original).hexdigest()


def test_upload_unknown_resumes_same_durable_file_identity_without_duplicate(finished):
    f, cfg, drive = finished
    drive.interrupt_after_upload = True
    first = Worker(f.c, f.lab, f.model, delivery=ReportDelivery(cfg, drive))
    assert first.once(cfg["campaign_id"]) == "DELIVERY_BLOCKED"
    # No retry in the worker loop. A separately resumed composition reconciles the same ID.
    drive.interrupt_after_upload = False
    second = Worker(f.c, f.lab, f.model, delivery=ReportDelivery(cfg, drive))
    assert second.once(cfg["campaign_id"]) == "FINALIZED"
    assert drive.allocations == 1 and drive.creates == 1
    with f.c.ledger.connect() as db:
        assert "private upstream body" not in str(f.c.ledger.read(db, cfg["campaign_id"]))


@pytest.mark.parametrize(
    "mutate",
    [
        lambda c: c.update(enabled=False),
        lambda c: c.update(folder_id="another-folder"),
        lambda c: c.update(approved_permission_ids=[]),
    ],
)
def test_delivery_cannot_be_enabled_or_redirected_by_unapproved_config(finished, mutate):
    f, cfg, drive = finished
    mutate(cfg)
    with pytest.raises(InvalidArtifact):
        ReportDelivery(cfg, drive)
    assert drive.creates == 0


@pytest.mark.parametrize(
    "mutate",
    [
        lambda d: d.files[BENCHMARK_FOLDER].update(
            permissions=[{"id": "public", "type": "anyone"}]
        ),
        lambda d: d.files[BENCHMARK_FOLDER].update(capabilities={"canAddChildren": False}),
        lambda d: d.files[BENCHMARK_FOLDER].update(permissions=[{"id": "unknown", "type": "user"}]),
    ],
)
def test_private_access_is_verified_before_upload(finished, mutate):
    f, cfg, drive = finished
    mutate(drive)
    with pytest.raises(InvalidArtifact):
        ReportDelivery(cfg, drive).deliver(f.c, cfg["campaign_id"])
    assert drive.creates == 0


def test_download_mismatch_never_becomes_delivered(finished):
    f, cfg, drive = finished
    drive.download = lambda *a: b"tampered"
    worker = Worker(f.c, f.lab, f.model, delivery=ReportDelivery(cfg, drive))
    assert worker.once(cfg["campaign_id"]) == "DELIVERY_BLOCKED"
    with f.c.ledger.connect() as db:
        assert f.c.state(db, cfg["campaign_id"])["delivery"]["status"] == "PREPARED"


def test_default_finalization_never_accesses_drive(finished):
    f, cfg, drive = finished
    assert f.worker.once(cfg["campaign_id"]) == "FINALIZED"
    assert drive.allocations == 0 and drive.creates == 0
