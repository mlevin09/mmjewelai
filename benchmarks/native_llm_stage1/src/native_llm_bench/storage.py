"""Private, atomic, append-only request/result files; one executor per run."""

import contextlib
import fcntl
import hashlib
import os
import subprocess
import tempfile
import uuid
from pathlib import Path

from .contracts import canonical, digest, load, require
from .transport import now


def write(path, value, *, replace=False):
    path = Path(path)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix=".pending-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(canonical(value) + b"\n")
            stream.flush()
            os.fsync(stream.fileno())
        if replace:
            os.replace(temp, path)
        else:
            os.link(temp, path)  # Existing evidence is never overwritten.
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        Path(temp).unlink(missing_ok=True)


def identity():
    root = Path(__file__).parent
    fingerprint = hashlib.sha256()
    for path in sorted(root.glob("*.py")):
        fingerprint.update(path.name.encode() + b"\0" + path.read_bytes())
    try:
        commit = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=root, stderr=subprocess.DEVNULL, text=True
        ).strip()
        dirty = bool(
            subprocess.check_output(
                [
                    "git",
                    "status",
                    "--porcelain",
                    "--untracked-files=all",
                    "--",
                    str(root.parent.parent),
                ],
                cwd=root,
                stderr=subprocess.DEVNULL,
                text=True,
            ).strip()
        )
    except (OSError, subprocess.CalledProcessError):
        commit, dirty = "UNKNOWN", None
    return {
        "commit_sha": commit,
        "source_sha256": fingerprint.hexdigest(),
        "working_tree_dirty": dirty,
    }


def create(root, plan):
    rid = uuid.uuid4().hex
    directory = Path(root) / rid
    directory.mkdir(mode=0o700, parents=True, exist_ok=False)
    run = {
        "schema_version": "1.0.0",
        "run_id": rid,
        "created_at": now(),
        "plan": plan,
        "plan_sha256": digest(plan),
        "runner": identity(),
    }
    write(directory / "run.json", run)
    return directory, run


@contextlib.contextmanager
def lock(directory):
    fd = os.open(Path(directory) / ".lock", os.O_CREAT | os.O_RDWR, 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            require(False, "run already has an active executor")
        yield
    finally:
        os.close(fd)


def read_run(directory):
    run = load(Path(directory) / "run.json")
    require(run["plan_sha256"] == digest(run["plan"]), "run plan integrity failure")
    return run


def files(directory, sid, tid, attempt):
    suffix = Path(sid) / tid / f"{attempt:04}.json"
    return Path(directory) / "requests" / suffix, Path(directory) / "results" / suffix


def attempts(directory, sid, tid):
    folder = Path(directory) / "requests" / sid / tid
    paths = sorted(folder.glob("*.json"))
    require(
        [p.stem for p in paths] == [f"{i:04}" for i in range(1, len(paths) + 1)],
        "noncontiguous request journal",
    )
    return len(paths)


def read_results(directory):
    """Only expected scoped paths are exported; unknown/orphan records fail closed."""
    run = read_run(directory)
    records = []
    expected_requests, expected_results = set(), set()
    for sid in run["plan"]["session_order"]:
        for tid in run["plan"]["turn_order"][sid]:
            for number in range(1, attempts(directory, sid, tid) + 1):
                req, res = files(directory, sid, tid, number)
                expected_requests.add(req)
                request = load(req)
                require(
                    request["session_id"] == sid
                    and request["turn_id"] == tid
                    and request["attempt"] == number
                    and request["request_sha256"] == digest(request["payload"]),
                    "request journal integrity failure",
                )
                from .instructions import validate_request_instruction

                validate_request_instruction(run["plan"], request)
                if res.exists():
                    expected_results.add(res)
                    result = load(res)
                    require(
                        result["session_id"] == sid
                        and result["turn_id"] == tid
                        and result["attempt"] == number,
                        "result journal scope failure",
                    )
                    records.append(result)
    require(
        set((Path(directory) / "requests").glob("*/*/*.json")) == expected_requests,
        "unscoped request journal",
    )
    require(
        set((Path(directory) / "results").glob("*/*/*.json")) == expected_results,
        "orphan result journal",
    )
    return run, records


def export(directory):
    run, results = read_results(directory)
    return {
        "schema_version": "1.0.0",
        "run": run,
        "attempt_results": results,
        "requests": [load(p) for p in sorted((Path(directory) / "requests").glob("*/*/*.json"))],
    }
