"""Forced-command native Runner job adapter. No shell or experimental algorithm."""

import base64
import fcntl
import hashlib
import math
import os
import re
import signal
import subprocess
import sys
import time
from dataclasses import replace
from pathlib import Path

from native_llm_bench import storage
from native_llm_bench.contracts import (
    Config,
    digest,
    execution_plan,
    keys,
    load,
    require,
    sha256_file,
    validate_manifest,
    validate_runtime,
)
from native_llm_bench.runner import _validate_result, execute
from native_llm_bench.transport import request as native_request

SOURCE = Path("/opt/jewelai-research-source")
WORK = Path("/home/jewelai-research/work")
MODEL_ROOT = Path("/opt/jewelai-llm-lab")
MAX_EXPORT = 8 * 1024**2


def attest_files(manifest):
    # Same fixed files/pins as the existing PrivateTunnel attestation; stream the
    # model so verification fits inside the non-root process's memory limit.
    for key, filename in (
        ("model_sha256", "Qwen3-1.7B-Q4_K_M.gguf"),
        ("runtime_sha256", "llama-server"),
    ):
        paths = [p for p in MODEL_ROOT.rglob(filename) if p.is_file() and not p.is_symlink()]
        require(len(paths) == 1, "native_runtime_file_not_unique")
        with paths[0].open("rb") as stream:
            require(
                hashlib.file_digest(stream, "sha256").hexdigest() == manifest[key],
                "native_runtime_file_mismatch",
            )


def _root(job_id):
    require(isinstance(job_id, str) and re.fullmatch("[a-f0-9]{64}", job_id), "invalid_native_job")
    root = WORK / ".native-runner" / job_id
    require(
        root.resolve().is_relative_to(WORK.resolve()) and not root.is_symlink(),
        "unsafe_native_job_path",
    )
    return root


def _validate(data):
    keys(
        data,
        (
            "job_id",
            "approval_sha256",
            "paths",
            "file_hashes",
            "runner_sha256",
            "config",
            "sessions",
            "plan_sha256",
            "deadline",
        ),
    )
    _root(data["job_id"])
    require(
        type(data["deadline"]) is int and 0 < data["deadline"] - time.time() <= 900,
        "native_job_deadline_invalid",
    )
    keys(data["paths"], ("runtime", "manifest"))
    paths = []
    for field in ("runtime", "manifest"):
        path = Path(data["paths"][field])
        require(
            path.is_absolute() and path.resolve().is_relative_to(SOURCE.resolve()),
            "native_source_path_not_allowed",
        )
        paths.append(path)
    require([sha256_file(p) for p in paths] == data["file_hashes"], "native_source_pin_mismatch")
    require(storage.identity()["source_sha256"] == data["runner_sha256"], "native_runner_changed")
    corpus, manifest = validate_runtime(load(paths[0])), validate_manifest(load(paths[1]))
    from .contracts import reserved

    chosen = data["sessions"]
    require(
        isinstance(chosen, list)
        and chosen
        and len(chosen) <= 20
        and all(isinstance(x, str) for x in chosen)
        and len(chosen) == len(set(chosen)),
        "invalid_native_selection",
    )
    selected = [s for s in corpus["sessions"] if s["session_id"] in chosen]
    require(
        len(selected) == len(chosen) and not any(reserved(s) for s in selected),
        "native_holdout_or_unknown_session",
    )
    config = Config(**data["config"]).validate(manifest)
    require(config.max_attempts == 1, "native_hidden_retries_not_allowed")
    plan = execution_plan(corpus, config, manifest, selected=chosen, exclude_holdouts=True)
    require(digest(plan) == data["plan_sha256"], "native_plan_mismatch")
    return corpus, config, manifest, plan


def handle(operation, args, *, launch=subprocess.Popen):
    if operation == "native_submit":
        _validate(args)
        root = _root(args["job_id"])
        root.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        lock_path = root.parent / ".submit.lock"
        with lock_path.open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            if root.exists():
                require(load(root / "request.json") == args, "native_job_idempotency_conflict")
                return status(args["job_id"])
            root.mkdir(mode=0o700)
            storage.write(root / "request.json", args)
            # A crash after this point is ambiguous. Existing request never starts twice.
            from .vm_guest import limits

            launch(
                [sys.executable, "-m", "jewelai_research.runner_guest", "--run", args["job_id"]],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
                preexec_fn=limits,
                env={
                    "PATH": "/usr/bin:/bin",
                    "HOME": "/home/jewelai-research",
                    "LANG": "C.UTF-8",
                    "PYTHONPATH": str(SOURCE) + ":" + str(SOURCE / "native_llm_stage1/src"),
                },
            )
        return {"job_id": args["job_id"], "status": "RUNNING"}
    if operation == "native_status":
        keys(args, ("job_id",))
        return status(args["job_id"])
    if operation == "native_result":
        keys(args, ("job_id", "offset"))
        require(
            type(args["offset"]) is int and 0 <= args["offset"] <= MAX_EXPORT,
            "invalid_native_export_offset",
        )
        root = _root(args["job_id"])
        receipt = load(root / "receipt.json")
        path = root / "export.json"
        require(
            path.stat().st_size <= MAX_EXPORT and sha256_file(path) == receipt["export_sha256"],
            "native_export_integrity",
        )
        with path.open("rb") as stream:
            stream.seek(args["offset"])
            chunk = stream.read(12288)
        return {
            "job_id": args["job_id"],
            "sha256": receipt["export_sha256"],
            "total_bytes": path.stat().st_size,
            "offset": args["offset"],
            "next_offset": args["offset"] + len(chunk),
            "data_base64": base64.b64encode(chunk).decode(),
            "eof": args["offset"] + len(chunk) >= path.stat().st_size,
        }
    raise ValueError("unsupported_native_operation")


def status(job_id):
    root = _root(job_id)
    request = load(root / "request.json")
    require(request["job_id"] == job_id, "native_job_scope")
    if (root / "receipt.json").exists():
        return load(root / "receipt.json")
    return {
        "job_id": job_id,
        "status": "RUNNING" if time.time() < request["deadline"] else "UNKNOWN",
        "plan_sha256": request["plan_sha256"],
        "runner_sha256": request["runner_sha256"],
    }


class DeadlineExpired(BaseException):
    pass


def run_job(job_id, *, transport=native_request):
    """Calls the existing Runner directly on the guest; never reimplements its loop."""
    root = _root(job_id)
    if (root / "receipt.json").exists():
        return load(root / "receipt.json")
    with (WORK / ".job.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            # Never overwrite the actual worker's terminal receipt on duplicate entry.
            return status(job_id)
        # Persist intent before any inference. Process restart cannot replay a paid job.
        if (root / "started.json").exists():
            return {"job_id": job_id, "status": "UNKNOWN"}
        storage.write(root / "started.json", {"at": time.time()})
        data = load(root / "request.json")
        receipt = {
            "job_id": job_id,
            "status": "UNKNOWN",
            "reason": "native_execution_interrupted",
            "plan_sha256": data["plan_sha256"],
            "runner_sha256": data["runner_sha256"],
        }
        start, attempts = time.time(), 0
        try:
            corpus, config, manifest, plan = _validate(data)
            if transport is native_request:
                # Offline fixtures cannot accidentally become real-loopback inference.
                from .contracts import MODEL, MODEL_SHA, RUNTIME_COMMIT, RUNTIME_SHA

                require(
                    manifest["verification_status"] == "NB08_ATTESTED"
                    and manifest["model_id"] == MODEL
                    and manifest["model_sha256"] == MODEL_SHA
                    and manifest["runtime_sha256"] == RUNTIME_SHA
                    and manifest["runtime_commit"] == RUNTIME_COMMIT,
                    "native_live_attestation_required",
                )
                attest_files(manifest)
            directory, _ = storage.create(root / "runs", plan)

            def bounded(cfg, payload):
                nonlocal attempts
                remaining = data["deadline"] - time.time()
                require(remaining > 0, "native_job_deadline_reached")
                require(
                    attempts < sum(len(t) for t in plan["turn_order"].values()),
                    "native_attempt_ceiling",
                )
                attempts += 1
                return transport(
                    replace(cfg, timeout_seconds=min(cfg.timeout_seconds, remaining)), payload
                )

            previous = signal.signal(
                signal.SIGALRM, lambda *_: (_ for _ in ()).throw(DeadlineExpired())
            )
            signal.alarm(max(1, math.ceil(data["deadline"] - time.time())))
            try:
                summary = execute(
                    corpus,
                    config,
                    manifest,
                    None,
                    selected=data["sessions"],
                    exclude_holdouts=True,
                    resume=directory,
                    retry_uncertain=False,
                    transport=bounded,
                )
            finally:
                signal.alarm(0)
                signal.signal(signal.SIGALRM, previous)
            exported = storage.export(directory)
            for result in exported["attempt_results"]:
                req, _ = storage.files(
                    directory, result["session_id"], result["turn_id"], result["attempt"]
                )
                _validate_result(load(req), result)
            require(
                len(__import__("json").dumps(exported).encode()) <= MAX_EXPORT,
                "native_export_limit",
            )
            storage.write(root / "export.json", exported)
            receipt = {
                "job_id": job_id,
                "status": summary["status"],
                "summary": summary,
                "plan_sha256": digest(plan),
                "runner_sha256": data["runner_sha256"],
                "export_sha256": sha256_file(root / "export.json"),
            }
        except (Exception, DeadlineExpired):
            # Never send Python/SSH/provider messages or error bodies into MCP/logs.
            pass
        finally:
            receipt.update(seconds=time.time() - start, attempts=attempts)
            storage.write(root / "receipt.json", receipt)
        return receipt


if __name__ == "__main__":
    import pwd

    require(
        os.geteuid() != 0 and pwd.getpwuid(os.geteuid()).pw_name == "jewelai-research",
        "dedicated_runner_account_required",
    )
    require(len(sys.argv) == 3 and sys.argv[1] == "--run", "invalid_native_guest_command")
    run_job(sys.argv[2])
