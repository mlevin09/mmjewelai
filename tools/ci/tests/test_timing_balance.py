"""Historical durations change scheduling only; all coverage/safety gates remain."""

import json
import xml.etree.ElementTree as ET
from copy import deepcopy

import pytest
from test_api_partitions import inventory, parts, reports_for
from test_api_timings import timing


def sealed(records):
    data = dict(version=1, cases=records)
    return {**data, "content_sha256": parts.digest(data)}


def measured(case, seconds):
    phases = dict(setup=0, call=seconds, teardown=0)
    return dict(
        module=case["module"],
        function=case["node_id"].split("::")[-1],
        basis="measured",
        milliseconds=seconds * 1000,
        phases=phases,
    )


def test_weighted_lpt_is_deterministic_and_never_moves_serial(tmp_path):
    items, review = inventory(tmp_path)
    weights = sealed({c["case_id"]: measured(c, 30 - i * 5) for i, c in enumerate(items)})
    (tmp_path / "tools/ci").mkdir(parents=True)
    (tmp_path / parts.TIMING_PATH).write_text(json.dumps(weights))
    plan = parts.make_plan(items, review, tmp_path, "revision", weights=weights)
    assert plan == parts.make_plan(items, review, tmp_path, "revision", weights=weights)
    assert plan["timing"]["projected_phase_milliseconds"] == {
        "isolated-0": 30000,
        "isolated-1": 25000,
        "isolated-2": 20000,
        "isolated-3": 0,
    }
    assert set(plan["partitions"]["serial"]) == {c["case_id"] for c in items[3:]}
    assert parts.selection(plan, "isolated-0", items, "revision", tmp_path)
    # Future unreviewed sources enter serial, not a smaller successful inventory.
    (tmp_path / "apps/api/tests/test_sample.py").write_text("# changed source\n")
    changed = parts.make_plan(items, review, tmp_path, "revision", weights=weights)
    assert len(changed["partitions"]["serial"]) == len(items)
    assert parts.gate(changed, reports_for(changed), ["success"] * 3)["result"] == "success"


@pytest.mark.parametrize("fault", ["checksum", "negative", "nan", "phase_cost", "witness", "basis"])
def test_bad_timing_cannot_produce_a_plan(tmp_path, fault):
    items, review = inventory(tmp_path)
    key = items[0]["case_id"]
    record = measured(items[0], 10)
    if fault == "negative":
        record["milliseconds"] = -1
    elif fault == "nan":
        record["phases"]["call"] = float("nan")
    elif fault == "phase_cost":
        record["milliseconds"] = 9
    elif fault == "witness":
        record.update(basis="function_profile_max", witness_case_id="f" * 64)
    elif fault == "basis":
        record["basis"] = "incomplete"
    weights = sealed({key: record})
    if fault == "checksum":
        weights["content_sha256"] = "0" * 64
    with pytest.raises(ValueError):
        parts.make_plan(items, review, tmp_path, "revision", weights=weights)


def test_timing_change_between_plan_and_selection_fails(tmp_path):
    items, review = inventory(tmp_path)
    weights = sealed({items[0]["case_id"]: measured(items[0], 10)})
    plan = parts.make_plan(items, review, tmp_path, "revision", weights=weights)
    with pytest.raises(ValueError, match="manifest changed"):
        parts.selection(plan, "isolated-0", items, "revision", tmp_path)


def artifacts(folder):
    case = dict(
        case_id="a" * 64,
        node_id="test::case",
        module="test",
        group="fast_api",
        complete=True,
        outcome="passed",
        phases=dict(setup=0.0, call=1.0, teardown=0.0),
        phase_counts=dict(setup=1, call=1, teardown=1),
    )
    return timing.write_reports(
        folder, [dict(case_id="a" * 64, group="fast_api")], {"a" * 64: case}, 0, 1
    )


@pytest.mark.parametrize("name", ["collection.json", "junit.xml", "summary.md", "timings.json"])
def test_all_required_artifacts_are_mandatory(tmp_path, name):
    report = artifacts(tmp_path)
    (tmp_path / name).unlink()
    with pytest.raises(ValueError, match="Missing"):
        parts.validate_artifacts(tmp_path, report)


@pytest.mark.parametrize("fault", ["collection", "junit_identity", "junit_count", "junit_failure"])
def test_inconsistent_artifacts_fail_closed(tmp_path, fault):
    report = artifacts(tmp_path)
    parts.validate_artifacts(tmp_path, report)
    if fault == "collection":
        (tmp_path / "collection.json").write_text("[]")
    else:
        p = tmp_path / "junit.xml"
        tree = ET.parse(p)
        suite = tree.getroot()
        if fault == "junit_identity":
            suite.find("testcase").set("name", "different")
        elif fault == "junit_count":
            suite.set("tests", "2")
        else:
            ET.SubElement(suite.find("testcase"), "failure", message="redacted")
        tree.write(p)
    with pytest.raises(ValueError):
        parts.validate_artifacts(tmp_path, report)


def test_unknown_report_or_product_failure_cannot_be_hidden(tmp_path):
    items, review = inventory(tmp_path)
    plan = parts.make_plan(items, review, tmp_path, "rev")
    reports = reports_for(plan)
    reports["unexpected"] = deepcopy(reports["serial"])
    assert parts.gate(plan, reports, ["success"] * 3)["result"] == "failure"
    del reports["unexpected"]
    reports["serial"]["testcases"][0]["outcome"] = "failed"
    assert parts.gate(plan, reports, ["success"] * 3)["result"] == "failure"


def test_new_f06_shaped_case_stays_required_without_trusting_historical_weights(tmp_path):
    items, review = inventory(tmp_path)
    weights = sealed({c["case_id"]: measured(c, 30 - i * 5) for i, c in enumerate(items)})
    before = parts.make_plan(items, review, tmp_path, "rev", weights=weights)
    module = "apps/api/tests/test_f06_new_output.py"
    (tmp_path / module).write_text("# new unreviewed fixture dependencies\n")
    extra = dict(
        case_id="f" * 64,
        node_id="test_f06_new_output.py::test_output",
        module=module,
        group="sqlite_integration",
        fixtures={},
    )
    after = parts.make_plan([*items, extra], review, tmp_path, "rev", weights=weights)
    assert after["cases"][extra["case_id"]]["partition"] == "serial"
    assert len(after["cases"]) == len(items) + 1
    for case, value in before["cases"].items():
        assert after["cases"][case] == value


def test_workflow_preserves_required_gate_postgres_identity_and_full_selection():
    from pathlib import Path

    # Structural guards for the deliberately fixed layout, not a YAML parser.
    # Full YAML syntax is validated separately without adding a product dependency.
    path = Path(__file__).resolve().parents[3] / ".github/workflows/full-regression.yml"
    text = path.read_text()
    runtime = text.split("\n  runtime:\n", 1)[1]
    isolated = text.split("\n  api_isolated:\n", 1)[1].split("\n  # Keep", 1)[0]
    assert text.startswith("name: Full Regression\n")
    assert "    needs: [prepare, api_isolated]" in runtime
    assert "    if: always()" in runtime
    assert "        image: postgres:16" in runtime
    assert "    timeout-minutes: 90" in runtime
    assert "      fail-fast: false" in isolated
    assert "partition: [isolated-0, isolated-1, isolated-2, isolated-3]" in isolated
    assert "services:" not in isolated
    assert runtime.index("verified_ci_postgres()") < runtime.index("alembic -c")
    assert "api_partitions.py gate" in runtime and "--upstream" in runtime
    assert "continue-on-error" not in text
    assert "workflow_dispatch:" in text
    assert "pull_request:" not in text and "push:" not in text and "schedule:" not in text
