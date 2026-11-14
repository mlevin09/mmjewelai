"""Durable, campaign-scoped lifecycle evidence; never infer ownership from VM name/status."""

import uuid

from native_llm_bench.contracts import digest, require

RECOVERABLE = {"START_SUBMITTED", "OWNED", "STOP_INTENT"}


class StartCancelled(RuntimeError):
    pass


class LeaseJournal:
    def __init__(self, controller, campaign_id, *, cancellation=lambda: False):
        self.c, self.cid = controller, campaign_id
        self.cancellation = cancellation

    def read(self):
        with self.c.ledger.connect() as db:
            return self.c.state(db, self.cid)["lease"]

    def cancelled(self):
        if self.cancellation():
            return True
        with self.c.ledger.connect() as db:
            s = self.c.state(db, self.cid)
            return s["stopped"] or self.c.clock() >= self.c.limits(s)["deadline"]

    def begin(self, envelope):
        with self.c.ledger.transaction() as db:
            s = self.c.state(db, self.cid)
            self.c.live_window(s)
            require(digest(envelope) == digest(s["envelope"]), "lease_envelope_mismatch")
            old = s["lease"]
            require(old is None or old["phase"] in {"RELEASED", "NO_START"}, "ownership_blocked")
            lease = {
                "lease_id": uuid.uuid4().hex,
                "campaign_id": self.cid,
                "phase": "CHECKING",
                "envelope_sha256": digest(envelope),
                "at": self.c.clock(),
            }
            self.c.ledger.append(db, self.cid, "LEASE", lease)
            self.c.ledger.append(
                db,
                self.cid,
                "CLEANUP",
                {
                    "verified_stopped": False,
                    "status": "PENDING",
                    "lease_id": lease["lease_id"],
                    "at": self.c.clock(),
                },
            )
            return lease

    def record(self, lease_id, phase, **facts):
        with self.c.ledger.transaction() as db:
            old = self.c.state(db, self.cid)["lease"]
            require(old and old["lease_id"] == lease_id, "lease_identity_mismatch")
            value = {**old, **facts, "phase": phase, "at": self.c.clock()}
            self.c.ledger.append(db, self.cid, "LEASE", value)
            return value

    def blocked(self, reason):
        old = self.read()
        if old:
            self.record(old["lease_id"], "BLOCKED", reason=reason)
        return {
            "verified_stopped": False,
            "status": "BLOCKED",
            "reason": reason,
            "lease_id": old["lease_id"] if old else None,
        }
