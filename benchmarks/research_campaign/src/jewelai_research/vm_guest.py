"""Forced-command guest helper. Installed root-owned; runs only as jewelai-research."""

import json
import os
import pwd
import re
import resource
import subprocess
import sys
import time
import uuid
from pathlib import Path

WORK = Path("/home/jewelai-research/work")
SOURCE = Path("/opt/jewelai-research-source")


def checked(path, *, writable=False):
    if not isinstance(path, str) or not path or len(path) > 1024:
        raise ValueError("invalid path")
    root = SOURCE if path.startswith("source/") else WORK
    relative = path.removeprefix("source/") if root == SOURCE else path
    p = (root / relative).resolve()
    if not p.is_relative_to(root) or (writable and root != WORK):
        raise ValueError("outside research environment")
    return p


def limits():
    resource.setrlimit(resource.RLIMIT_AS, (512 * 1024**2, 512 * 1024**2))
    resource.setrlimit(resource.RLIMIT_FSIZE, (64 * 1024**2, 64 * 1024**2))
    resource.setrlimit(resource.RLIMIT_NPROC, (64, 64))
    resource.setrlimit(resource.RLIMIT_NOFILE, (128, 128))


def handle(op, args):
    if op in {"native_submit", "native_status", "native_result"}:
        # Root-owned operator installation only. No caller-selected module or path.
        sys.path[:0] = [str(SOURCE), str(SOURCE / "native_llm_stage1/src")]
        from jewelai_research.runner_guest import handle as native_handle

        return native_handle(op, args)
    if op == "write":
        p = checked(args["path"], writable=True)
        data = args["content"].encode()
        if len(data) > 65536:
            raise ValueError("file too large")
        p.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        # Reject a raced directory symlink before opening; O_NOFOLLOW protects final entry.
        p = checked(args["path"], writable=True)
        fd = os.open(p, os.O_CREAT | os.O_TRUNC | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        return {"written_bytes": len(data)}
    if op == "read":
        p = checked(args["path"])
        with p.open("rb") as f:
            data = f.read(65537)
        return {"content": data[:65536].decode(errors="replace"), "truncated": len(data) > 65536}
    if op == "exec":
        command = args["command"]
        if not isinstance(command, str) or not 0 < len(command) <= 32768:
            raise ValueError("invalid command")
        job = uuid.uuid4().hex
        root = WORK / ".jobs" / job
        root.mkdir(parents=True, mode=0o700)
        (root / "command").write_text(command)
        subprocess.Popen(
            [sys.executable, __file__, "--job", job],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        return {"job_id": job, "status": "RUNNING"}
    if op == "job":
        job = args["job_id"]
        if not isinstance(job, str) or not re.fullmatch("[a-f0-9]{32}", job):
            raise ValueError("invalid job")
        root = WORK / ".jobs" / job
        result = root / "result.json"
        return (
            json.loads(result.read_text())
            if result.exists()
            else {"job_id": job, "status": "RUNNING"}
        )
    raise ValueError("unsupported operation")


def job_run(job):
    if not re.fullmatch("[a-f0-9]{32}", job):
        raise ValueError("invalid job")
    root = checked(".jobs/" + job)
    import fcntl

    lock = (WORK / ".job.lock").open("a")
    try:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        (root / "result.json").write_text(json.dumps({"job_id": job, "status": "BUSY"}))
        return
    start = time.time()
    env = {
        "PATH": "/usr/local/bin:/usr/bin:/bin",
        "HOME": "/home/jewelai-research",
        "PYTHONPATH": str(SOURCE / "native_llm_stage1/src"),
        "LANG": "C.UTF-8",
    }
    with (root / "stdout").open("wb") as out, (root / "stderr").open("wb") as err:
        p = subprocess.Popen(
            ["/bin/bash", "--noprofile", "--norc", "-c", (root / "command").read_text()],
            cwd=WORK,
            env=env,
            stdout=out,
            stderr=err,
            preexec_fn=limits,
            start_new_session=True,
        )
        try:
            code, status = p.wait(timeout=900), "COMPLETED"
        except subprocess.TimeoutExpired:
            import signal

            os.killpg(p.pid, signal.SIGKILL)
            code, status = p.wait(), "TIMEOUT"
    result = {"job_id": job, "status": status, "exit_code": code, "seconds": time.time() - start}
    for name in ("stdout", "stderr"):
        with (root / name).open("rb") as f:
            data = f.read(65537)
        result[name] = data[:65536].decode(errors="replace")
        result[name + "_truncated"] = len(data) > 65536
    temp = root / "result.pending"
    temp.write_text(json.dumps(result))
    temp.replace(root / "result.json")


if __name__ == "__main__":
    try:
        if os.geteuid() == 0 or pwd.getpwuid(os.geteuid()).pw_name != "jewelai-research":
            raise ValueError("dedicated non-root account required")
        if len(sys.argv) == 3 and sys.argv[1] == "--job":
            job_run(sys.argv[2])
        else:
            data = sys.stdin.buffer.read(100001)
            if len(data) > 100000:
                raise ValueError("request too large")
            req = json.loads(data)
            print(json.dumps(handle(req["operation"], req["arguments"])))
    except Exception:
        print('{"error":"guest_access_rejected"}')
        sys.exit(1)
