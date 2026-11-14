"""Single-host durable append-only ledger. SQL transactions, not agent memory, authorize work."""

import contextlib
import os
import sqlite3
from pathlib import Path

from native_llm_bench.contracts import canonical, decode, digest, require


class Ledger:
    def __init__(self, root):
        self.root = Path(root)
        require(
            not any((p / ".git").exists() for p in self.root.resolve().parents),
            "private_store_must_be_outside_git",
        )
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        require(not self.root.is_symlink(), "unsafe_store")
        require(self.root.stat().st_mode & 0o077 == 0, "store_must_be_private")
        self.path = self.root / "campaign.sqlite3"
        if not self.path.exists():
            fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            os.close(fd)
        require(
            not self.path.is_symlink() and self.path.stat().st_mode & 0o077 == 0,
            "ledger_must_be_private",
        )
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS events (
                    seq INTEGER PRIMARY KEY, campaign TEXT NOT NULL,
                    kind TEXT NOT NULL, body BLOB NOT NULL,
                    previous TEXT NOT NULL, sha TEXT UNIQUE NOT NULL);
                CREATE TRIGGER IF NOT EXISTS no_update BEFORE UPDATE ON events
                    BEGIN SELECT RAISE(ABORT, 'append only'); END;
                CREATE TRIGGER IF NOT EXISTS no_delete BEFORE DELETE ON events
                    BEGIN SELECT RAISE(ABORT, 'append only'); END;
            """)

    @contextlib.contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        db.execute("PRAGMA synchronous=FULL")
        try:
            yield db
        finally:
            db.close()

    @contextlib.contextmanager
    def transaction(self):
        with self.connect() as db:
            try:
                db.execute("BEGIN IMMEDIATE")
                yield db
                db.commit()
            except BaseException:
                db.rollback()
                raise

    def read(self, db, campaign):
        rows = db.execute(
            "SELECT kind,body,previous,sha FROM events WHERE campaign=? ORDER BY seq", (campaign,)
        ).fetchall()
        previous, result = "0" * 64, []
        for kind, body, before, sha in rows:
            body = decode(body)
            event = {"campaign": campaign, "kind": kind, "body": body, "previous": before}
            require(before == previous and sha == digest(event), "ledger_integrity")
            previous = sha
            result.append({**event, "sha256": sha})
        return result

    def append(self, db, campaign, kind, body):
        events = self.read(db, campaign)
        event = {
            "campaign": campaign,
            "kind": kind,
            "body": body,
            "previous": events[-1]["sha256"] if events else "0" * 64,
        }
        db.execute(
            "INSERT INTO events(campaign,kind,body,previous,sha) VALUES(?,?,?,?,?)",
            (campaign, kind, canonical(body), event["previous"], digest(event)),
        )


def projection(events):
    require(events and events[0]["kind"] == "ACTIVATED", "unknown_campaign")
    result = {
        "envelope": events[0]["body"]["envelope"],
        "created_at": events[0]["body"]["at"],
        "experiments": {},
        "calls": {},
        "stopped": False,
        "cleanup": None,
        "report": None,
        "lease": None,
        "delivery": None,
        "delivery_failure": None,
    }
    for event in events[1:]:
        b, kind = event["body"], event["kind"]
        if kind == "REGISTERED":
            result["experiments"][b["experiment_id"]] = {**b, "status": "REGISTERED"}
        elif kind in ("QUEUED", "RUNNING", "RESULT"):
            result["experiments"][b["experiment_id"]].update(b)
        elif kind == "STOP":
            result["stopped"] = True
        elif kind == "CLEANUP":
            result["cleanup"] = b
        elif kind == "LEASE":
            result["lease"] = b
        elif kind == "DELIVERY":
            result["delivery"] = b
            if b["status"] == "DELIVERED":
                result["delivery_failure"] = None
        elif kind == "DELIVERY_BLOCKED":
            result["delivery_failure"] = b
        elif kind == "FINALIZED":
            result["report"] = b
        elif kind == "CALL":
            result["calls"][b["key"]] = b
    return result
