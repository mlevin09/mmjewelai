import hashlib
import importlib.util
import json
import os
import signal
import subprocess
import sys
import threading
import xml.etree.ElementTree as ET
from copy import deepcopy
from pathlib import Path

import pytest
from test_api_timings import CANARY, invoke

SCRIPT = Path(__file__).resolve().parents[1] / "api_partitions.py"
SPEC = importlib.util.spec_from_file_location("api_partitions", SCRIPT)
parts = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(parts)


def inventory(root):
    folder = root / "apps/api/tests"
    folder.mkdir(parents=True)
    (folder / "conftest.py").write_text("# reviewed disposable fixture\n")
    (folder / "test_sample.py").write_text("# imports no external or shared state\n")
    result = []
    for i, group in enumerate(
        ("sqlite_integration", "fast_api", "heavy_f05", "postgres_integration", "other_review")
    ):
        result.append(
            dict(
                case_id=hashlib.sha256(str(i).encode()).hexdigest(),
                node_id=f"tests/test_sample.py::test_case_{i}",
                module="apps/api/tests/test_sample.py",
                group=group,
                fixtures={},
            )
        )
    pins = parts.test_sources(root, result[0]["module"], {})
    return result, {p: [sha] for p, sha in pins.items()}


def reports_for(plan):
    return {
        p: dict(
            selection=dict(
                partition=p,
                plan_sha256=parts.digest(plan),
                inventory_sha256=plan["inventory_sha256"],
                expected_count=len(ids),
            ),
            collected=len(ids),
            collection_ids=ids,
            exitcode=0,
            diagnostics=[],
            testcases=[
                dict(
                    case_id=x,
                    complete=True,
                    outcome="passed",
                    phases=dict(setup=0.01, call=0.02, teardown=0.01),
                    phase_counts=dict(setup=1, call=1, teardown=1),
                )
                for x in ids
            ],
            wall_seconds=1,
        )
        for p, ids in plan["partitions"].items()
    }


def test_partition_is_deterministic_complete_and_unknown_sources_are_serial(tmp_path):
    items, review = inventory(tmp_path)
    first = parts.make_plan(items, review, tmp_path, "revision")
    assert first == parts.make_plan(items, review, tmp_path, "revision")
    union = [x for ids in first["partitions"].values() for x in ids]
    assert len(union) == len(set(union)) == len(items)
    assert set(union) == {x["case_id"] for x in items}
    assert first["partitions"]["serial"] == sorted(x["case_id"] for x in items[3:])
    assert parts.selection(first, "serial", items, "revision", tmp_path) == set(
        first["partitions"]["serial"]
    )
    (tmp_path / "apps/api/tests/conftest.py").write_text("# fixture changed: not reviewed\n")
    changed = parts.make_plan(items, review, tmp_path, "revision")
    assert len(changed["partitions"]["serial"]) == len(items)
    with pytest.raises(ValueError, match="sources changed"):
        parts.selection(first, "serial", items, "revision", tmp_path)


def test_invalid_inventory_plan_or_revision_fails_closed(tmp_path):
    items, review = inventory(tmp_path)
    with pytest.raises(ValueError, match="Duplicate"):
        parts.make_plan(items + items[:1], review, tmp_path, "rev")
    plan = parts.make_plan(items, review, tmp_path, "rev")
    with pytest.raises(ValueError, match="revision"):
        parts.selection(plan, "serial", items, "different", tmp_path)
    with pytest.raises(ValueError, match="inventory"):
        parts.selection(plan, "serial", items[:-1], "rev", tmp_path)
    plan["partitions"]["serial"].append(items[0]["case_id"])
    with pytest.raises(ValueError, match="overlap"):
        parts.validate_plan(plan)


def test_new_nested_test_source_cannot_escape_the_source_identity_guard(tmp_path):
    items, review = inventory(tmp_path)
    plan = parts.make_plan(items, review, tmp_path, "rev")
    folder = tmp_path / "apps/api/tests/nested"
    folder.mkdir()
    (folder / "test_added.py").write_text("# new unreviewed source\n")
    with pytest.raises(ValueError, match="sources changed"):
        parts.selection(plan, "serial", items, "rev", tmp_path)


def test_aggregate_accepts_only_complete_required_partition_results(tmp_path):
    items, review = inventory(tmp_path)
    plan = parts.make_plan(items, review, tmp_path, "rev")
    report = parts.gate(plan, reports_for(plan), ["success"] * 3)
    assert report["result"] == "success"
    assert report["expected"] == report["reported"] == len(items)


@pytest.mark.parametrize(
    "fault",
    [
        "missing_partition",
        "missing_case",
        "duplicate_case",
        "wrong_selection",
        "checksum",
        "inventory",
        "failed",
        "cancelled",
        "skipped_job",
        "missing_job_result",
        "unexpected_skip",
        "incomplete",
        "missing_phase",
        "duplicate_phase",
        "diagnostic",
        "nonzero",
        "invalid_duration",
        "collected_count",
    ],
)
def test_aggregate_rejects_each_missing_or_nonpassing_boundary(tmp_path, fault):
    items, review = inventory(tmp_path)
    plan = parts.make_plan(items, review, tmp_path, "rev")
    reports = reports_for(plan)
    upstream = ["success"] * 3
    report = reports["serial"]
    case = report["testcases"][0]
    if fault == "missing_partition":
        del reports["isolated-0"]
    elif fault == "missing_case":
        report["testcases"].pop()
    elif fault == "duplicate_case":
        report["testcases"].append(deepcopy(case))
    elif fault == "wrong_selection":
        report["collection_ids"] = []
    elif fault == "checksum":
        report["selection"]["plan_sha256"] = "0" * 64
    elif fault == "inventory":
        report["selection"]["inventory_sha256"] = "0" * 64
    elif fault in ("failed", "cancelled", "skipped_job"):
        upstream[1] = fault
    elif fault == "missing_job_result":
        upstream.pop()
    elif fault == "unexpected_skip":
        case["outcome"] = "skipped"
    elif fault == "incomplete":
        case["complete"] = False
    elif fault == "missing_phase":
        del case["phases"]["call"]
    elif fault == "duplicate_phase":
        case["phase_counts"]["call"] = 2
    elif fault == "diagnostic":
        report["diagnostics"] = [dict(kind="collection_error")]
    elif fault == "nonzero":
        report["exitcode"] = 124
    elif fault == "invalid_duration":
        case["phases"]["call"] = float("nan")
    elif fault == "collected_count":
        report["collected"] = 0
    assert parts.gate(plan, reports, upstream)["result"] == "failure"


def test_actual_selector_runs_original_ids_once_and_rejects_wrong_checksum(tmp_path):
    source = f'''
import pytest
@pytest.mark.parametrize("value", ["{CANARY}", "public"])
def test_selected(value): pass
def test_not_selected(): raise RuntimeError("must never run")
'''
    collected, output, _ = invoke(tmp_path, source, collect=True)
    assert collected.returncode == 0
    items = json.loads((output / "collection.json").read_text())
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    plan = parts.make_plan(items, {}, Path.cwd(), revision)
    selected = {x["case_id"] for x in items if "test_selected" in x["node_id"]}
    plan["partitions"]["serial"] = sorted(set(plan["partitions"]["serial"]) - selected)
    plan["partitions"]["isolated-0"] = sorted(selected)
    for identity in selected:
        plan["cases"][identity]["partition"] = "isolated-0"
    path = tmp_path / "plan.json"
    path.write_text(json.dumps(plan))
    args = ["--plan", str(path), "--partition", "isolated-0", "--plan-sha256", parts.digest(plan)]
    result, output, private = invoke(tmp_path, source, extra=args)
    assert result.returncode == 0
    report = json.loads((output / "timings.json").read_text())
    assert set(report["collection_ids"]) == selected
    assert len(report["testcases"]) == len(private) == 2
    assert all(
        x["complete"] and x["phase_counts"] == dict(setup=1, call=1, teardown=1)
        for x in report["testcases"]
    )
    assert CANARY not in result.stdout + "".join(p.read_text() for p in output.iterdir())
    args[3] = "isolated-3"  # An explicit required empty partition still emits a bound receipt.
    empty, output, _ = invoke(tmp_path, source, extra=args)
    assert empty.returncode == 0
    empty_report = json.loads((output / "timings.json").read_text())
    assert empty_report["selection"]["expected_count"] == 0
    assert empty_report["testcases"] == []
    args[-1] = "0" * 64
    bad, output, _ = invoke(tmp_path, source, extra=args)
    assert bad.returncode != 0
    assert ET.parse(output / "junit.xml").find("testcase/error") is not None


@pytest.mark.parametrize("mode", ["timeout", "interrupt"])
def test_bounded_interruption_records_incomplete_failure_without_payload(tmp_path, mode):
    source = (
        "import time\ndef test_wait(): time.sleep(10)"
        if mode == "timeout"
        else f'def test_interrupt(): raise KeyboardInterrupt("{CANARY}")'
    )
    extra = ["--timeout-seconds", "1.2"] if mode == "timeout" else []
    result, output, _ = invoke(tmp_path, source, extra=extra)
    assert result.returncode == (124 if mode == "timeout" else 2)
    report = json.loads((output / "timings.json").read_text())
    assert report["diagnostics"]
    assert ET.parse(output / "junit.xml").find("testcase/error") is not None
    assert CANARY not in result.stdout + "".join(p.read_text() for p in output.iterdir())


def test_parent_interrupt_stops_test_process_and_writes_failure_receipt(tmp_path):
    timing = SCRIPT.parent / "api_timings.py"
    test = tmp_path / "test_signal.py"
    test.write_text("import time\ndef test_wait(): time.sleep(10)\n")
    config = tmp_path / "pytest.ini"
    config.write_text("[pytest]\n")
    output = tmp_path / "report"
    process = subprocess.Popen(
        [sys.executable, str(timing), "--output", str(output), "--", "-c", str(config), str(test)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env={**os.environ, "PYTEST_ADDOPTS": ""},
    )
    watchdog = threading.Timer(6, process.terminate)
    watchdog.start()
    try:
        assert process.stdout.readline().startswith("START ")
        process.send_signal(signal.SIGINT)
        process.communicate(timeout=8)
        assert process.returncode == 130
        assert json.loads((output / "timings.json").read_text())["diagnostics"]
    finally:
        watchdog.cancel()
        if process.poll() is None:
            process.kill()
            process.wait()
