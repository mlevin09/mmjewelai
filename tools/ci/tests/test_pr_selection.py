"""Bounded selector, execution and qualification tests; no product/PG fixtures."""

import hashlib
import json
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import full_units
import pr_checks
import pr_selection as selection
import qualification
from test_api_timings import CANARY
from test_api_timings import invoke as tiny_pytest

ROOT = Path(__file__).resolve().parents[3]
CONFIG = json.loads((ROOT / "tools/ci/pr_routes.json").read_text())
SHA = "a" * 40


def selected(*paths):
    return selection.build_selection(ROOT, paths, CONFIG, source_sha=SHA, merge_base="b" * 40)


def targets(manifest):
    return {t for group in manifest["suites"].values() for t in group["targets"]}


def test_description_routes_with_whole_changed_test_file_and_smoke():
    path = "apps/api/tests/test_ifp_capacity_runtime.py"
    # This actual existing file's whole native collection includes any added params.
    result = selected("packages/prompts/src/jewelai_prompts/description.py", path)
    assert path in targets(result)
    assert "packages/prompts/tests" in targets(result)
    assert CONFIG["smoke"][0] in targets(result)
    assert result["blocked_reasons"] == []
    assert not result["full_regression_required"]


def test_parser_includes_downstream_integration():
    result = selected("packages/parser/src/jewelai_parser/full_message.py")
    assert {"packages/parser/tests", "apps/api/tests/test_parsed_enrichment.py"} <= targets(result)


@pytest.mark.parametrize(
    "path,bucket",
    [
        ("packages/domain/src/jewelai_domain/preservation.py", "continuation"),
        ("packages/persistence/alembic/versions/new.py", "persistence"),
        ("packages/domain/src/jewelai_domain/models.py", "domain"),
        ("apps/api/tests/disposable_postgres.py", "persistence"),
        ("pyproject.toml", "authorization"),
        ("requirements.txt", "authorization"),
    ],
)
def test_critical_sources_keep_mandatory_checks_and_full_gate(path, bucket):
    result = selected(path)
    assert bucket in result["buckets"]
    assert result["full_regression_required"]
    assert result["suites"]["api"]["targets"]
    assert (
        "apps/api/tests/test_keep_atomicity.py::test_rejected_final_snapshot_rolls_back_all_staged_rows_and_pin"
        in targets(result)
    )


def test_docs_and_web_do_not_claim_product_execution():
    docs = selected("docs/example.md")
    assert docs["docs_only"] and not docs["suites"] and not docs["relevant"]
    web = selected("apps/web/src/config.ts")
    assert not web["docs_only"] and not web["relevant"] and not web["suites"]
    assert "Web" in web["delegated_check"]


@pytest.mark.parametrize(
    "path",
    ["new/runtime.py", "apps/api/tests/new-fixture.json", "apps/api/tests/unknown_helper.py"],
)
def test_unknown_impact_fails_explicitly_with_smoke_still_present(path):
    result = selected(path)
    assert result["blocked_reasons"] and targets(result)


def test_missing_mapping_target_and_external_paths_fail():
    config = deepcopy(CONFIG)
    config["smoke"] = ["apps/api/tests/does_not_exist.py"]
    with pytest.raises(ValueError, match="missing_required"):
        selection.build_selection(ROOT, ["unknown.py"], config, source_sha=SHA, merge_base=SHA)
    with pytest.raises(ValueError, match="invalid_changed_path"):
        selected("../outside.py")
    assert selection.normalize(["a/test.py::test_x", "a", "a/test.py"]) == ["a"]


def test_transitive_local_test_helper_dependency(tmp_path):
    folder = tmp_path / "apps/api/tests"
    folder.mkdir(parents=True)
    (folder / "helper.py").write_text("VALUE = 1\n")
    (folder / "helper2.py").write_text("from helper import VALUE\n")
    (folder / "test_values.py").write_text("from helper2 import VALUE\n")
    assert selection.dependent_tests(tmp_path, ["apps/api/tests/helper.py"]) == [
        "apps/api/tests/test_values.py"
    ]


def test_merge_base_covers_all_feature_commits_not_only_last(tmp_path):
    def git(*args):
        return subprocess.check_output(["git", *args], cwd=tmp_path, text=True).strip()

    git("init", "-q")
    git("config", "user.email", "ci@example.invalid")
    git("config", "user.name", "Synthetic CI fixture")
    (tmp_path / "base").write_text("base")
    git("add", ".")
    git("commit", "-qm", "base")
    base = git("rev-parse", "HEAD")
    git("checkout", "-qb", "feature")
    for name in ("first.py", "last.py"):
        (tmp_path / name).write_text("# fixture\n")
        git("add", name)
        git("commit", "-qm", name)
    head = git("rev-parse", "HEAD")
    git("checkout", "-qb", "target", base)
    (tmp_path / "target-only").write_text("target")
    git("add", ".")
    git("commit", "-qm", "target advanced")
    merge, paths = selection.git_changes(tmp_path, git("rev-parse", "HEAD"), head)
    assert merge == base
    assert paths == ["first.py", "last.py"]


def test_parser_13_version_exception_is_exact_and_fails_closed(tmp_path):
    path = "packages/domain/src/jewelai_domain/preservation_release.py"
    source = tmp_path / path
    source.parent.mkdir(parents=True)
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "ci@example.invalid"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "Synthetic CI"], cwd=tmp_path, check=True)
    source.write_text('parse_version: Literal["1.2.0"]\nOTHER = "unchanged"\n')
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "base"], cwd=tmp_path, check=True)
    base = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=tmp_path, text=True).strip()
    source.write_text('parse_version: Literal["1.2.0", "1.3.0"]\nOTHER = "unchanged"\n')
    subprocess.run(["git", "commit", "-qam", "exact addition"], cwd=tmp_path, check=True)
    good = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=tmp_path, text=True).strip()
    assert selection.is_exact_parser_13_release_version_widening(tmp_path, base, good, path)
    source.write_text('parse_version: Literal["1.2.0", "1.3.0"]\nOTHER = "changed"\n')
    subprocess.run(["git", "commit", "-qam", "unrelated edit"], cwd=tmp_path, check=True)
    bad = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=tmp_path, text=True).strip()
    assert not selection.is_exact_parser_13_release_version_widening(tmp_path, base, bad, path)
    assert not selection.is_exact_parser_13_release_version_widening(
        tmp_path, base, good, "packages/domain/src/jewelai_domain/preservation.py"
    )
    assert not selection.is_exact_parser_13_release_version_widening(tmp_path, "f" * 40, good, path)


def test_frozen_parser13_risk_profile_is_strict_and_protects_core_checks():
    merge_base = "ef656c70f341940183905eca890b507ee2f457e8"
    # Positive control is the reviewed immutable release, not an arbitrary later CI/feature HEAD.
    current = "4ca9490acbb103758aa34103388e0890e12e991e"
    raw = subprocess.check_output(
        ["git", "diff", "--name-only", merge_base, current], cwd=ROOT, text=True
    )
    changed = raw.splitlines()
    assert selection.is_exact_parser13_recovery_release(ROOT, changed, merge_base, current)
    assert not selection.is_exact_parser13_recovery_release(
        ROOT, changed + ["apps/api/src/unapproved.py"], merge_base, current
    )
    assert not selection.is_exact_parser13_recovery_release(ROOT, changed, "a" * 40, current)
    assert not selection.is_exact_parser13_recovery_release(ROOT, changed, merge_base, "f" * 40)
    assert len(selection.PARSER13_RECOVERY_API_TESTS) == len(
        set(selection.PARSER13_RECOVERY_API_TESTS)
    )
    assert {
        "apps/api/tests/completion/test_studio_recovery.py",
        "apps/api/tests/test_f05_mutation_safety.py",
        "apps/api/tests/test_parser12_contract.py",
        "apps/api/tests/test_f05_release_http.py",
    }.issubset(selection.PARSER13_RECOVERY_API_TESTS)
    assert "apps/api/tests/test_generation_preparations_postgres.py" not in (
        selection.PARSER13_RECOVERY_API_TESTS
    )


def test_other_preservation_changes_keep_full_regression_gate():
    result = selected("packages/domain/src/jewelai_domain/preservation_release.py")
    assert result["full_regression_required"]
    assert "continuation" in result["buckets"]
    assert "evidence" in result["buckets"]
    assert "persistence" in result["buckets"]


def passed_report():
    case = "a" * 64
    return dict(
        exitcode=0,
        diagnostics=[],
        collection_ids=[case],
        testcases=[
            dict(
                case_id=case,
                complete=True,
                outcome="passed",
                phases=dict(setup=0.0, call=1.0, teardown=0.0),
                phase_counts=dict(setup=1, call=1, teardown=1),
            )
        ],
    )


@pytest.mark.parametrize(
    "fault",
    ["failed", "skipped", "missing", "duplicate", "incomplete", "phase", "diagnostic", "exit"],
)
def test_selected_execution_fail_closed(fault):
    report = passed_report()
    expected = report["collection_ids"][:]
    if fault in {"failed", "skipped"}:
        report["testcases"][0]["outcome"] = fault
    elif fault == "missing":
        report["testcases"] = []
    elif fault == "duplicate":
        report["testcases"] *= 2
    elif fault == "incomplete":
        report["testcases"][0]["complete"] = False
    elif fault == "phase":
        report["testcases"][0]["phase_counts"]["call"] = 2
    elif fault == "diagnostic":
        report["diagnostics"] = ["bounded"]
    else:
        report["exitcode"] = 1
    with pytest.raises(ValueError):
        pr_checks.verify_execution(report, expected)


@pytest.mark.parametrize("fault", ["failed", "collection"])
def test_real_small_pytest_failure_reaches_pr_gate_safely(tmp_path, fault):
    source = f'def test_bad():\n    assert False, "{CANARY}"\n'
    if fault == "collection":
        source = f'raise ValueError("{CANARY}")\n'
    child, folder, _ = tiny_pytest(tmp_path, source)
    assert child.returncode != 0
    report = json.loads((folder / "timings.json").read_text())
    with pytest.raises(ValueError):
        pr_checks.verify_execution(report, report["collection_ids"])
    assert CANARY not in child.stdout + child.stderr + (folder / "timings.json").read_text()


def test_changed_existing_file_collects_new_parametrized_cases(tmp_path):
    child, folder, _ = tiny_pytest(
        tmp_path,
        """
import pytest
@pytest.mark.parametrize("value", [1, 2, 3])
def test_new_case(value):
    assert value > 0
""",
    )
    assert child.returncode == 0
    report = json.loads((folder / "timings.json").read_text())
    assert len(report["collection_ids"]) == 3
    pr_checks.verify_execution(report, report["collection_ids"])


def unit_proof():
    return {
        name: dict(targets=group["targets"], case_ids=[hashlib.sha256(name.encode()).hexdigest()])
        for name, group in full_units.SCOPES.items()
    }


def meta():
    return dict(
        id=10,
        run_attempt=1,
        head_sha=SHA,
        event="workflow_dispatch",
        status="completed",
        conclusion="success",
        path=qualification.WORKFLOW,
        repository=dict(full_name=qualification.REPOSITORY),
    )


def receipt():
    return qualification.emit(
        dict(source_revision=SHA, cases={"a" * 64: {}}),
        dict(result="success", errors=[], expected=1, reported=1),
        sha=SHA,
        run_id=10,
        attempt=1,
        authorization="synthetic Owner approval reference",
        reason="test",
        unit_suites=unit_proof(),
    )


@pytest.mark.parametrize(
    "fault",
    [
        "different_sha",
        "failed",
        "cancelled",
        "pr_event",
        "wrong_workflow",
        "wrong_repo",
        "missing_proof",
        "bad_hash",
        "missing_units",
        "missing_api",
    ],
)
def test_missing_or_invalid_exact_release_qualification_blocks(fault):
    evidence, metadata = receipt(), meta()
    qualification.validate_qualification(evidence, metadata, SHA)
    if fault == "different_sha":
        metadata["head_sha"] = "b" * 40
    elif fault in {"failed", "cancelled"}:
        metadata["conclusion"] = fault
    elif fault == "pr_event":
        metadata["event"] = "pull_request"
    elif fault == "wrong_workflow":
        metadata["path"] = ".github/workflows/runtime-api.yml"
    elif fault == "wrong_repo":
        metadata["repository"]["full_name"] = "someone/fork"
    elif fault == "missing_proof":
        evidence = {}
    elif fault == "bad_hash":
        evidence["content_sha256"] = "0" * 64
    else:
        evidence["unit_suites" if fault == "missing_units" else "api_cases"] = (
            {} if fault == "missing_units" else []
        )
        evidence["content_sha256"] = selection.digest(
            {k: v for k, v in evidence.items() if k != "content_sha256"}
        )
    with pytest.raises(ValueError):
        qualification.validate_qualification(evidence, metadata, SHA)


def test_high_risk_keeps_critical_execution_and_blocks_without_full(monkeypatch, tmp_path):
    manifest = selected("packages/domain/src/jewelai_domain/preservation.py")
    monkeypatch.setattr(pr_checks, "validate_selection", lambda *a: None)
    calls = []

    def invoke(*args, **kwargs):
        calls.append(kwargs)
        report = passed_report()
        report["wall_seconds"] = 950  # Above ordinary budget, still mandatory.
        if args[3] == ["apps/api/tests"]:
            report["collection_ids"].append("b" * 64)
        return report

    monkeypatch.setattr(pr_checks, "invoke", invoke)
    monkeypatch.setattr(pr_checks, "validate_artifacts", lambda *a: None)
    with pytest.raises(ValueError, match="manual_full_qualification_required"):
        pr_checks.execute(ROOT, manifest, tmp_path)
    result = json.loads((tmp_path / "pr-result.json").read_text())
    assert not result["qualified_by_full"] and result["result"] == "failure"
    assert len([c for c in calls if not c.get("collect")]) == len(manifest["suites"])


def test_full_inventory_and_qualification_cover_all_existing_families():
    full_units.audit_inventory(ROOT)
    proof = unit_proof()
    full_units.check_proof(proof)
    assert full_units.covers(
        proof, selected("packages/prompts/src/jewelai_prompts/description.py")["suites"]
    )
    proof.pop("packages/parser")
    with pytest.raises(ValueError):
        full_units.check_proof(proof)


def test_workflow_manual_only_and_required_runtime_not_skipped():
    full = (ROOT / ".github/workflows/full-regression.yml").read_text()
    trigger = full.split("on:\n", 1)[1].split("permissions:", 1)[0]
    assert "workflow_dispatch:" in trigger
    assert all(
        t not in trigger
        for t in ["schedule:", "push:", "pull_request:", "workflow_call:", "workflow_run:"]
    )
    runtime = (ROOT / ".github/workflows/runtime-api.yml").read_text()
    assert runtime.startswith("name: Runtime API\n")
    assert "jobs:\n  runtime:\n    runs-on:" in runtime
    assert "continue-on-error" not in runtime and "paths:" not in runtime
    assert "pull_request:\n    branches: [jewelai-v2]" in runtime
    assert "full-regression.yml" not in runtime  # No dispatching the full workflow.
    for source in (full, runtime):
        assert "from disposable_postgres import verified_ci_postgres" in source
        assert source.index("verified_ci_postgres()") < source.index("alembic -c")
    isolated = full.split("  api_isolated:", 1)[1].split("  # Keep", 1)[0]
    assert "TEST_POSTGRES_URL" not in isolated
    assert "if: always()" in full
