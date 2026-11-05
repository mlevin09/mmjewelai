"""FIX-01..08: fixture content is behavior, not extension-only documentation."""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pr_checks
import pr_selection as selection
from test_pr_selection import ROOT, selected, targets


@pytest.mark.parametrize(
    "path",
    [
        "docs/architecture/design.txt",
        "README.md",
        "packages/prompts/README.md",
        "specs/prompts/README.md",
    ],
)
def test_fix01_genuine_documentation_stays_lightweight(path):
    result = selected(path)
    assert result["docs_only"] and not result["relevant"] and not result["suites"]


@pytest.mark.parametrize("suffix", ["txt", "md", "rst"])
def test_fix02_03_05_unmapped_text_fixture_blocks(suffix):
    result = selected(f"apps/api/tests/unknown_resource.{suffix}")
    assert not result["docs_only"] and result["relevant"]
    assert "unmapped_fixture_data" in result["blocked_reasons"]


@pytest.mark.parametrize(
    "path",
    [
        "data/prompts/runtime_template.txt",
        "packages/prompts/src/templates/input.md",
        "unmapped/runtime.rst",
        "docs/fixtures/input.md",
    ],
)
def test_fix03_runtime_resource_is_not_exempted_by_extension(path):
    result = selected(path)
    assert not result["docs_only"] and result["relevant"]
    assert result["suites"] or result["blocked_reasons"]
    if path.startswith(("unmapped/", "docs/fixtures/")):
        assert result["blocked_reasons"]


def scratch_repo(root, *, owned=False):
    ci = root / "tools/ci"
    ci.mkdir(parents=True)
    for source in (ROOT / "tools/ci").glob("*.py"):
        shutil.copyfile(source, ci / source.name)
    base_tests = root / "apps/api/tests"
    tests = base_tests / "owned" if owned else base_tests
    tests.mkdir(parents=True)
    (root / "apps/api/pyproject.toml").write_text(
        '[tool.pytest.ini_options]\ntestpaths = ["tests"]\n'
    )
    (tests / "expected_value.txt").write_text("approved")
    (tests / "test_consumer.py").write_text(
        "from pathlib import Path\ndef test_value():\n"
        '    assert Path(__file__).with_name("expected_value.txt").read_text()'
        '.strip() == "approved"\n'
    )
    (base_tests / "test_smoke.py").write_text("def test_smoke():\n    assert True\n")
    (base_tests / "test_unrelated.py").write_text("def test_unrelated():\n    assert True\n")
    config = dict(
        version=1,
        smoke=["apps/api/tests/test_smoke.py"],
        buckets={},
        routes=[],
        full_required_prefixes=[],
        build_files=[],
        delegated_prefixes=[],
        delegated_check=None,
    )
    if owned:
        config["fixture_scopes"] = [
            dict(
                resources="apps/api/tests/owned",
                tests="apps/api/tests/owned",
                evidence=(
                    "Disposable self-contained namespace: every fixture consumer "
                    "is inside this complete test directory."
                ),
            )
        ]
    (ci / "pr_routes.json").write_text(json.dumps(config))

    def git(*args):
        return subprocess.check_output(["git", *args], cwd=root, text=True).strip()

    git("init", "-q")
    git("config", "user.email", "fixture-ci@example.invalid")
    git("config", "user.name", "Disposable fixture test")
    git("add", ".")
    git("commit", "-qm", "synthetic baseline")
    return config, git


def test_fix04_06_real_fixture_only_commits_cannot_false_green(tmp_path):
    config, git = scratch_repo(tmp_path, owned=True)
    fixture = tmp_path / "apps/api/tests/owned/expected_value.txt"
    base = git("rev-parse", "HEAD")
    outcomes = []
    # A compatible fixture-only commit really executes its consumer successfully.
    # A second fixture-only commit breaks the unchanged consumer and must fail CI.
    for label, content in [("compatible", "approved\n"), ("broken", "broken")]:
        fixture.write_text(content)
        git("add", "apps/api/tests/owned/expected_value.txt")
        git("commit", "-qm", label)
        head = git("rev-parse", "HEAD")
        merge_base, changed = selection.git_changes(tmp_path, base, head)
        manifest = selection.build_selection(
            tmp_path, changed, config, source_sha=head, merge_base=merge_base
        )
        direct = pr_checks.invoke(
            tmp_path,
            tmp_path / (label + "-consumer-collection"),
            "apps/api/pyproject.toml",
            ["apps/api/tests/owned/test_consumer.py"],
            collect=True,
        )
        # This must precede the assertion that fails on the old selector, so the
        # RED receipt proves the actual false-green, not only a selector mismatch.
        if label == "broken" or manifest["docs_only"]:
            try:
                raw = pr_checks.invoke(
                    tmp_path,
                    tmp_path / (label + "-consumer"),
                    "apps/api/pyproject.toml",
                    ["apps/api/tests/owned/test_consumer.py"],
                )
                consumer = "passed" if raw["exitcode"] == 0 else "failed"
            except ValueError:
                consumer = "failed"
        else:
            consumer = "passed (verified by selected gate below)"
        folder = tmp_path / (label + "-gate")
        try:
            result = pr_checks.execute(tmp_path, manifest, folder)
            gate = result["result"]
        except ValueError:
            gate = json.loads((folder / "pr-result.json").read_text())["result"]
        outcomes.append(
            dict(
                fixture_commit=head,
                baseline=base,
                changed=changed,
                manifest=manifest,
                consumer=consumer,
                consumer_case_ids=direct["collection_ids"],
                gate=gate,
            )
        )
    if destination := os.getenv("FIXTURE_ROUTING_EVIDENCE_DIR"):
        path = Path(destination)
        path.mkdir(parents=True, exist_ok=True)
        (path / "fixture-only-journey.json").write_text(json.dumps(outcomes, indent=2))
    assert outcomes[1]["consumer"] == "failed"
    assert outcomes[1]["gate"] == "failure", "broken fixture was falsely accepted"
    assert outcomes[0]["gate"] == "success"
    for outcome in outcomes:
        assert not outcome["manifest"]["docs_only"]
        assert "apps/api/tests/owned" in targets(outcome["manifest"])
        assert not outcome["manifest"]["blocked_reasons"]


def test_fix07_08_changed_tests_source_and_critical_routes_remain():
    result = selected(
        "packages/parser/src/jewelai_parser/full_message.py",
        "apps/api/tests/test_f06_output_opt_in.py",
    )
    assert "packages/parser/tests" in targets(result)
    assert "apps/api/tests/test_f06_output_opt_in.py" in targets(result)
    critical = selected("packages/domain/src/jewelai_domain/preservation.py")
    assert critical["full_regression_required"]
    assert {"continuation", "evidence", "persistence"} <= set(critical["buckets"])


@pytest.mark.parametrize("mode", ["helper", "ambiguous", "readme", "deleted"])
def test_known_fixture_ownership_is_conservative(tmp_path, mode):
    config, _ = scratch_repo(tmp_path)
    folder = tmp_path / "apps/api/tests"
    path = "apps/api/tests/expected_value.txt"
    if mode == "helper":
        (folder / "test_consumer.py").write_text(
            'from reader import read\ndef test_value():\n    assert read() == "approved"\n'
        )
        (folder / "reader.py").write_text(
            "from pathlib import Path\ndef read():\n"
            '    return Path(__file__).with_name("expected_value.txt").read_text()\n'
        )
    elif mode == "ambiguous":
        (folder / "other").mkdir()
        (folder / "other/expected_value.txt").write_text("ambiguous")
    elif mode == "readme":
        path = "apps/api/tests/README.md"
        (folder / "README.md").write_text("fixture, despite conventional documentation name")
        (folder / "test_consumer.py").write_text(
            "from pathlib import Path\ndef test_value():\n"
            '    assert Path(__file__).with_name("README.md").read_text()\n'
        )
    else:
        (folder / "expected_value.txt").unlink()
    result = selection.build_selection(
        tmp_path, [path], config, source_sha="a" * 40, merge_base="b" * 40
    )
    assert result["relevant"] and not result["docs_only"]
    # Reader recognition is no longer permission to pass without an owning scope.
    assert "unmapped_fixture_data" in result["blocked_reasons"]
    assert result["fixture_dependencies"][path]["coverage"] == "unmapped"
