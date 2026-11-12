"""Explicitly enabled private final-report outbox; no default Drive access or sharing writes."""

import hashlib
import http.client
import re
from urllib.parse import urlencode

from native_llm_bench.contracts import canonical, decode, digest, keys, require

BENCHMARK_FOLDER = "1AQzcmYZJNRpPHx-PktnKGEBhZ7FKt9cj"
DRIVE_ID = re.compile(r"[A-Za-z0-9_-]{1,200}\Z")


class DriveClient:
    """Fixed Drive REST operations. Token comes from approved host OAuth composition only."""

    def __init__(self, access_token):
        self.access_token = access_token  # callable; never persisted, logged or returned

    def _request(self, method, path, body=None, content_type="application/json", limit=4_000_000):
        connection = http.client.HTTPSConnection("www.googleapis.com", timeout=15)
        try:
            connection.request(
                method,
                path,
                body,
                {"Authorization": "Bearer " + self.access_token(), "Content-Type": content_type},
            )
            response = connection.getresponse()
            raw = response.read(limit + 1)
            require(
                len(raw) <= limit and response.status in {200, 201, 404, 409},
                "drive_request_failed",
            )
            return response.status, raw
        finally:
            connection.close()

    def metadata(self, file_id):
        require(isinstance(file_id, str) and DRIVE_ID.fullmatch(file_id), "invalid_drive_identity")
        status, raw = self._request(
            "GET",
            "/drive/v3/files/"
            + file_id
            + "?"
            + urlencode(
                {
                    "fields": "id,mimeType,parents,appProperties,permissions(id,type),"
                    "capabilities(canAddChildren)"
                }
            ),
        )
        return None if status == 404 else decode(raw)

    def allocate(self):
        status, raw = self._request(
            "GET", "/drive/v3/files/generateIds?count=1&space=drive&type=files"
        )
        data = decode(raw)
        require(status == 200 and len(data["ids"]) == 1, "drive_allocation_failed")
        return data["ids"][0]

    def create(self, file_id, folder, payload, sha):
        boundary = "jewelai-campaign-" + sha
        meta = {
            "id": file_id,
            "name": "JewelAI-campaign-" + sha[:16] + ".json",
            "mimeType": "application/json",
            "parents": [folder],
            "appProperties": {"jewelaiReportSha256": sha},
        }
        body = (
            b"--"
            + boundary.encode()
            + b"\r\nContent-Type: application/json\r\n\r\n"
            + canonical(meta)
            + b"\r\n--"
            + boundary.encode()
            + b"\r\nContent-Type: application/json\r\n\r\n"
            + payload
            + b"\r\n--"
            + boundary.encode()
            + b"--\r\n"
        )
        self._request(
            "POST",
            "/upload/drive/v3/files?uploadType=multipart",
            body,
            "multipart/related; boundary=" + boundary,
        )

    def download(self, file_id, maximum):
        require(isinstance(file_id, str) and DRIVE_ID.fullmatch(file_id), "invalid_drive_identity")
        status, raw = self._request(
            "GET", "/drive/v3/files/" + file_id + "?alt=media", limit=maximum
        )
        require(status == 200, "drive_download_failed")
        return raw


class ReportDelivery:
    def __init__(self, config, client):
        keys(
            config,
            (
                "enabled",
                "campaign_id",
                "envelope_sha256",
                "folder_id",
                "maximum_bytes",
                "approved_permission_ids",
            ),
        )
        require(
            config["enabled"] is True and config["folder_id"] == BENCHMARK_FOLDER,
            "report_delivery_not_authorized",
        )
        require(
            type(config["maximum_bytes"]) is int and 0 < config["maximum_bytes"] <= 4_000_000,
            "invalid_delivery_limit",
        )
        require(
            isinstance(config["approved_permission_ids"], list)
            and config["approved_permission_ids"]
            and all(isinstance(x, str) and x for x in config["approved_permission_ids"]),
            "private_permissions_not_configured",
        )
        self.config, self.client = config.copy(), client

    def _private(self, meta):
        require(isinstance(meta, dict) and meta.get("permissions"), "drive_access_not_verified")
        require(
            all(
                p.get("type") in {"user", "group"}
                and p.get("id") in self.config["approved_permission_ids"]
                for p in meta["permissions"]
            ),
            "drive_access_not_private",
        )

    def deliver(self, controller, cid):
        cfg = self.config
        require(cid == cfg["campaign_id"], "delivery_campaign_mismatch")
        with controller.ledger.transaction() as db:
            state = controller.state(db, cid)
            require(
                digest(state["envelope"]) == cfg["envelope_sha256"], "delivery_envelope_mismatch"
            )
            require(state["report"] is not None, "report_not_finalized")
            if state["delivery"] and state["delivery"]["status"] == "DELIVERED":
                return state["delivery"]
        controller.verify_report(cid)
        payload = (controller.directory(cid) / "report.json").read_bytes()
        require(
            hashlib.sha256(payload).hexdigest() == state["report"]["report_sha256"],
            "report_integrity",
        )
        require(len(payload) <= cfg["maximum_bytes"], "delivery_payload_too_large")
        sha = hashlib.sha256(payload).hexdigest()
        folder = self.client.metadata(cfg["folder_id"])
        self._private(folder)
        require(
            folder.get("id") == cfg["folder_id"]
            and folder.get("mimeType") == "application/vnd.google-apps.folder"
            and folder.get("capabilities", {}).get("canAddChildren") is True,
            "drive_folder_write_not_authorized",
        )
        prepared = state["delivery"]
        if prepared:
            require(
                prepared["sha256"] == sha and prepared["config_sha256"] == digest(cfg),
                "delivery_resume_mismatch",
            )
            file_id = prepared["file_id"]
        else:
            file_id = self.client.allocate()
            require(
                isinstance(file_id, str) and DRIVE_ID.fullmatch(file_id), "invalid_drive_identity"
            )
            with controller.ledger.transaction() as db:
                require(controller.state(db, cid)["delivery"] is None, "delivery_already_claimed")
                controller.ledger.append(
                    db,
                    cid,
                    "DELIVERY",
                    {
                        "status": "PREPARED",
                        "file_id": file_id,
                        "sha256": sha,
                        "bytes": len(payload),
                        "config_sha256": digest(cfg),
                    },
                )
        meta = self.client.metadata(file_id)
        if meta is None:
            self.client.create(file_id, cfg["folder_id"], payload, sha)
            meta = self.client.metadata(file_id)
        self._private(meta)
        require(
            meta.get("id") == file_id
            and meta.get("parents") == [cfg["folder_id"]]
            and meta.get("appProperties", {}).get("jewelaiReportSha256") == sha,
            "drive_report_scope_mismatch",
        )
        downloaded = self.client.download(file_id, cfg["maximum_bytes"])
        require(downloaded == payload, "drive_report_byte_mismatch")
        result = {
            "status": "DELIVERED",
            "file_id": file_id,
            "sha256": sha,
            "bytes": len(payload),
            "config_sha256": digest(cfg),
            "url": "https://drive.google.com/file/d/" + file_id + "/view",
        }
        with controller.ledger.transaction() as db:
            controller.ledger.append(db, cid, "DELIVERY", result)
        return result
