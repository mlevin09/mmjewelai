import json
import os
import subprocess
import sys
import threading
from dataclasses import asdict
from http.server import HTTPServer
from pathlib import Path

from conftest import FIXTURES
from synthetic_server import Handler

ROOT = Path(__file__).parents[1]


def invoke(*args):
    env = {**os.environ, "PYTHONPATH": str(ROOT / "src")}
    result = subprocess.run(
        [sys.executable, "-m", "native_llm_bench", *map(str, args)],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=15,
    )
    return result, json.loads(result.stdout)


def test_offline_preview_run_inspect_resume_export(endpoint, tmp_path):
    config = tmp_path / "config.json"
    config.write_text(json.dumps(asdict(endpoint.config)))
    common = [
        "--runtime",
        FIXTURES / "synthetic.runtime.json",
        "--config",
        config,
        "--model-manifest",
        FIXTURES / "synthetic.model.json",
    ]
    r, value = invoke("validate", "--runtime", FIXTURES / "synthetic.runtime.json")
    assert r.returncode == 0 and value["user_turns"] == 7
    r, plan = invoke("plan", *common, "--sessions", "SYN5")
    assert r.returncode == 0 and plan["session_order"] == ["SYN5"]
    assert not endpoint.requests
    r, run = invoke("run", *common, "--sessions", "SYN5", "--output", tmp_path / "runs")
    assert r.returncode == 0 and run["status"] == "COMPLETED"
    directory = run["run_directory"]
    assert len(endpoint.requests) == 5
    r, result = invoke("resume", directory, *common)
    assert r.returncode == 0 and result["status"] == "COMPLETED"
    assert len(endpoint.requests) == 5
    r, result = invoke("inspect", directory)
    assert r.returncode == 0 and result["completed_turns"] == 5
    out = tmp_path / "export.json"
    r, result = invoke("export", directory, "--output", out)
    assert r.returncode == 0
    exported = json.loads(out.read_text())
    assert len(exported["requests"]) == len(exported["attempt_results"]) == 5
    r, result = invoke("export", directory, "--output", out)
    assert r.returncode == 64 and result["detail"] == "FileExistsError"


def test_documented_synthetic_server_cli(tmp_path):
    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    config = json.loads((FIXTURES / "synthetic.config.json").read_text())
    config["endpoint"] = f"http://127.0.0.1:{server.server_port}"
    path = tmp_path / "demo-config.json"
    path.write_text(json.dumps(config))
    try:
        r, run = invoke(
            "run",
            "--runtime",
            FIXTURES / "synthetic.runtime.json",
            "--config",
            path,
            "--model-manifest",
            FIXTURES / "synthetic.model.json",
            "--sessions",
            "SYN2,SYN5",
            "--output",
            tmp_path / "demo-runs",
        )
        assert r.returncode == 0 and run["status"] == "COMPLETED"
        r, exported = invoke("export", run["run_directory"], "--output", tmp_path / "demo.json")
        assert r.returncode == 0
        records = json.loads((tmp_path / "demo.json").read_text())["attempt_results"]
        assert len(records) == 7
        assert all(
            x["assistant_message"]["content"].startswith("SYNTHETIC acknowledgment")
            for x in records
        )
        assert all(x["metrics"]["completion_tokens"] is None for x in records)
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
