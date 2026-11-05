import importlib.util
import json
import os
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "api_timings.py"
SPEC = importlib.util.spec_from_file_location("api_timings", SCRIPT)
timing = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(timing)
CANARY = "PRIVATE_CANARY_user_text_token_request_body"


def invoke(tmp_path, source, *, collect=False, extra=()):
    test = tmp_path / "test_probe.py"
    test.write_text(source)
    config = tmp_path / "pytest.ini"
    config.write_text("[pytest]\n")
    output = tmp_path / "reports"
    private = tmp_path / "private-nodes.json"
    command = [
        sys.executable,
        str(SCRIPT),
        "--output",
        str(output),
        "--private-manifest",
        str(private),
    ]
    command += list(extra)
    command += ["--", "-c", str(config), str(test)] + (["--collect-only"] if collect else [])
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=20,
        env={**os.environ, "PYTEST_ADDOPTS": ""},
    )
    return result, output, json.loads(private.read_text()) if private.exists() else []


def assert_partition(collection, summary):
    grouped = [node for group in summary["groups"].values() for node in group]
    assert len(grouped) == len(set(grouped)) == len(collection)
    assert set(grouped) == {node["case_id"] for node in collection}


def test_safe_pass_failure_skip_reports_and_exit_status(tmp_path):
    source = f'''
import pytest
@pytest.mark.parametrize("value", ["{CANARY}", "public"])
def test_parameter(value, capfd, request):
    request.node.user_properties.append(("http_evidence", "{CANARY}"))
    with capfd.disabled():
        print("{CANARY}")
    assert value == "public", "{CANARY}"
def test_skip():
    pytest.skip("{CANARY}")
'''
    result, output, private = invoke(tmp_path, source)
    assert result.returncode == 1
    public = result.stdout + result.stderr + "".join(f.read_text() for f in output.iterdir())
    assert CANARY not in public
    assert CANARY in json.dumps(private)
    assert "START " in result.stdout and "AssertionError" in result.stdout
    collection = json.loads((output / "collection.json").read_text())
    summary = json.loads((output / "timings.json").read_text())
    assert summary["outcomes"] == {"failed": 1, "passed": 1, "skipped": 1}
    assert not summary["unexecuted_or_incomplete"]
    assert_partition(collection, summary)
    junit = ET.parse(output / "junit.xml").getroot()
    assert len(junit.findall("testcase")) == 3
    assert len(junit.findall("testcase/failure")) == 1
    assert len(junit.findall("testcase/skipped")) == 1
    assert float(junit.get("time")) > 0
    assert all(set(c["phases"]) == {"setup", "call", "teardown"} for c in summary["slowest_30"])
    assert private[0]["case_id"] != private[1]["case_id"]
    assert (output / "summary.md").read_text().count("Slowest 30") == 1


def test_collection_does_not_execute_and_preserves_parameters(tmp_path):
    result, output, private = invoke(
        tmp_path,
        """
import pytest
@pytest.fixture
def forbidden():
    raise RuntimeError("fixture must not execute")
@pytest.mark.parametrize("value", range(4))
def test_no_execution(forbidden, value):
    raise AssertionError("test must not execute")
""",
        collect=True,
    )
    assert result.returncode == 0
    collection = json.loads((output / "collection.json").read_text())
    summary = json.loads((output / "timings.json").read_text())
    assert len(private) == len(collection) == 4
    assert summary["outcomes"] == {} and len(summary["unexecuted_or_incomplete"]) == 4
    assert_partition(collection, summary)


@pytest.mark.parametrize(
    "source,expected",
    [
        ("def test_pass(): pass", 0),
        (f'raise RuntimeError("{CANARY}")', 2),
        (
            f'import pytest\n@pytest.fixture\ndef bad(): raise ValueError("{CANARY}")\n'
            "def test_setup(bad): pass",
            1,
        ),
        (
            'import pytest\n@pytest.fixture\ndef bad():\n yield\n raise ValueError("hidden")\n'
            "def test_teardown(bad): pass",
            1,
        ),
    ],
)
def test_nonzero_exits_and_fixture_failures_are_not_hidden(tmp_path, source, expected):
    result, output, _ = invoke(tmp_path, source)
    assert result.returncode == expected
    assert CANARY not in result.stdout + result.stderr
    assert json.loads((output / "timings.json").read_text())["exitcode"] == expected


def test_ownership_uses_resolved_fixture_not_only_marker():
    assert (
        timing.group_for(
            "x.py", {"engine": "apps/api/tests/test_generation_preparations_postgres.py"}, False
        )[0]
        == "postgres_integration"
    )
    assert timing.group_for("x.py", {}, True)[0] == "postgres_integration"
    assert timing.group_for("test_z_f05_review_native.py", {}, False)[0] == "heavy_f05"
    assert (
        timing.group_for("x.py", {"engine": "apps/api/tests/conftest.py"}, False)[0]
        == "sqlite_integration"
    )
    assert timing.group_for("unknown.py", {}, False)[0] == "other_review"


def test_duplicate_collection_fails_closed_and_incomplete_is_not_pass(tmp_path):
    entry = dict(case_id="id", node_id="test_x", module="m", group="other_review")
    with pytest.raises(ValueError, match="Duplicate"):
        timing.write_reports(tmp_path, [entry, entry], {}, 0, 1)
    summary = timing.write_reports(
        tmp_path,
        [entry],
        {
            "id": dict(
                **entry,
                phases={"setup": 0.1},
                outcome="passed",
                complete=False,
            )
        },
        2,
        1,
    )
    assert summary["outcomes"] == {"incomplete": 1}
    assert summary["unexecuted_or_incomplete"] == ["id"]
    assert ET.parse(tmp_path / "junit.xml").find("testcase/error") is not None


def test_top_30_and_module_totals_use_all_three_phases(tmp_path):
    collection = [
        dict(case_id=str(i), node_id=f"test_{i}", module="m", group="other_review")
        for i in range(35)
    ]
    cases = {
        e["case_id"]: dict(
            **e,
            phases=dict(setup=1, call=int(e["case_id"]), teardown=2),
            outcome="passed",
            complete=True,
        )
        for e in collection
    }
    summary = timing.write_reports(tmp_path, collection, cases, 0, 1)
    assert len(summary["slowest_30"]) == 30
    assert summary["slowest_30"][0]["case_id"] == "34"
    assert summary["modules"]["m"] == dict(tests=35, seconds=sum(range(35)) + 105)
    assert_partition(collection, summary)


def test_fixture_error_is_explicit_in_junit_and_timings(tmp_path):
    result, output, _ = invoke(
        tmp_path,
        """
import pytest
@pytest.fixture
def bad():
    yield
    pytest.skip("private teardown message")
def test_failed(bad):
    assert False, "private call message"
""",
    )
    assert result.returncode == 1
    summary = json.loads((output / "timings.json").read_text())
    assert summary["outcomes"] == {"failed": 1}
    assert summary["slowest_30"][0]["failures"] == [
        dict(phase="call", exception_family="AssertionError")
    ]
