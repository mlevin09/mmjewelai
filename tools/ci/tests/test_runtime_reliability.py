"""Issue #171: exercise existing native CLI paths, not a separate test harness."""

import json
import os
import subprocess
import sys

import pytest
from test_fixture_routing import scratch_repo
from test_pr_selection import CONFIG, ROOT, selected, selection, targets


def component_repo(root):
    _, git = scratch_repo(root)
    folder = root / "apps/stt/tests"
    folder.mkdir(parents=True)
    (folder.parent / "pyproject.toml").write_text(
        '[tool.pytest.ini_options]\ntestpaths=["tests"]\n'
    )
    (folder / "test_transcription.py").write_text(
        'import pytest\n@pytest.mark.parametrize("language", ["ru", "en"])\n'
        'def test_transcription(language):\n    assert language in ("ru", "en")\n'
    )
    (root / "tools/ci/pr_routes.json").write_text(json.dumps(CONFIG))
    git("add", ".")
    git("commit", "-qm", "reviewed isolated app fixture")
    return git, folder


@pytest.mark.parametrize("change", ["source", "pyproject", "lock", "fixture"])
def test_stt_owns_complete_scope_without_shared_smoke_or_database(tmp_path, change):
    git, folder = component_repo(tmp_path)
    path = {
        "source": "apps/stt/src/app.py",
        "pyproject": "apps/stt/pyproject.toml",
        "lock": "apps/stt/requirements-linux.lock",
        "fixture": "apps/stt/tests/fixtures/audio.wav",
    }[change]
    manifest = selection.build_selection(
        tmp_path, [path], CONFIG, source_sha=git("rev-parse", "HEAD"), merge_base="b" * 40
    )
    assert targets(manifest) == {"apps/stt/tests"}
    assert not manifest["blocked_reasons"] and not manifest["full_regression_required"]
    assert not manifest["needs_database"]
    environment = selection.execution_environment(manifest, CONFIG)
    assert environment == dict(
        backend=False, packages=["-e", "./apps/stt[test]", "numpy==2.2.6"], lint_roots=["apps/stt"]
    )
    assert all(x not in str(environment) for x in ("[model]", "cuda", "torch", "apps/api"))


@pytest.mark.parametrize(
    "path",
    [
        "apps/web/src/App.tsx",
        "infra/terraform/preprod/stt.tf",
        ".github/workflows/deploy-preprod.yml",
        "docs/audit.md",
    ],
)
def test_unrelated_paths_need_no_runtime_environment(path):
    manifest = selected(path)
    assert not manifest["relevant"] and not manifest["suites"] and not manifest["needs_database"]
    assert selection.execution_environment(manifest, CONFIG) == dict(
        backend=False, packages=[], lint_roots=[]
    )


def test_ci_only_changes_do_not_collect_api_or_install_backend():
    manifest = selected("tools/ci/pr_selection.py", ".github/workflows/runtime-api.yml")
    assert set(manifest["suites"]) == {"ci"}
    assert not manifest["needs_database"] and not manifest["full_regression_required"]
    assert selection.execution_environment(manifest, CONFIG)["packages"] == [
        "pytest>=8.4,<9",
        "ruff>=0.12,<1",
    ]


def test_unknown_app_scope_is_not_inferred_or_silently_ignored(tmp_path):
    path = tmp_path / "apps/unreviewed/tests/test_new.py"
    path.parent.mkdir(parents=True)
    path.write_text("def test_new(): pass\n")
    with pytest.raises(ValueError, match="unsupported_test_scope"):
        selection.build_selection(
            tmp_path,
            ["apps/unreviewed/tests/test_new.py"],
            CONFIG,
            source_sha="a" * 40,
            merge_base="b" * 40,
        )


@pytest.mark.parametrize(
    "fault,status",
    [("pass", "PASS"), ("fail", "FAIL"), ("collection", "BLOCKED"), ("skip", "BLOCKED")],
)
def test_actual_isolated_native_execution_and_failures(tmp_path, fault, status):
    git, folder = component_repo(tmp_path)
    base = git("rev-parse", "HEAD")
    source = folder / "test_transcription.py"
    if fault == "fail":
        source.write_text('def test_failed():\n    assert False, "PRIVATE_PAYLOAD"\n')
    elif fault == "collection":
        source.write_text('raise RuntimeError("PRIVATE_PAYLOAD")\n')
    elif fault == "skip":
        source.write_text(
            'import pytest\ndef test_skipped():\n    pytest.skip("PRIVATE_PAYLOAD")\n'
        )
    else:
        source.write_text(source.read_text() + "\n# compatible change\n")
    git("add", ".")
    git("commit", "-qm", "bounded scenario")
    head = git("rev-parse", "HEAD")
    selected_file = tmp_path / "selection.json"
    cli = subprocess.run(
        [
            sys.executable,
            "tools/ci/pr_selection.py",
            "--base",
            base,
            "--head",
            head,
            "--output",
            str(selected_file),
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert cli.returncode == 0
    result = subprocess.run(
        [
            sys.executable,
            "tools/ci/pr_checks.py",
            "--manifest",
            str(selected_file),
            "--output",
            str(tmp_path / "gate"),
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=30,
    )
    receipt = json.loads((tmp_path / "gate/pr-result.json").read_text())
    assert receipt["status"] == status
    assert (result.returncode == 0) == (fault == "pass")
    assert "PRIVATE_PAYLOAD" not in result.stdout + result.stderr + json.dumps(receipt)
    assert not (tmp_path / "gate/api-native-inventory").exists()
    if fault == "pass":
        assert receipt["groups"]["apps/stt"]["selected"] == 2


def test_no_tests_cli_works_without_site_packages_and_cache(tmp_path):
    git, _ = component_repo(tmp_path)
    base = git("rev-parse", "HEAD")
    path = tmp_path / "apps/web/src/change.tsx"
    path.parent.mkdir(parents=True)
    path.write_text("// synthetic web change\n")
    git("add", ".")
    git("commit", "-qm", "web only")
    head = git("rev-parse", "HEAD")
    manifest = tmp_path / "selection.json"
    for script, args in [
        ("pr_selection.py", ["--base", base, "--head", head, "--output", str(manifest)]),
        ("pr_checks.py", ["--manifest", str(manifest), "--output", str(tmp_path / "gate")]),
    ]:
        result = subprocess.run(
            [sys.executable, "-S", "tools/ci/" + script, *args],
            cwd=tmp_path,
            env={**os.environ, "PIP_CACHE_DIR": str(tmp_path / "absent-cache")},
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 0, result.stdout
    receipt = json.loads((tmp_path / "gate/pr-result.json").read_text())
    assert receipt["status"] == "NOT_APPLICABLE" and not receipt["groups"]
    assert not (tmp_path / "absent-cache").exists()
    workflow = (ROOT / ".github/workflows/runtime-api.yml").read_text()
    setup = workflow.split("      - uses: actions/setup-python@v5", 1)[1].split("      - name:", 1)[
        0
    ]
    assert "if: steps.selection.outputs.needs_tests == 'true'" in setup
    assert "cache: pip" in setup  # retained where dependencies really get installed
    assert workflow.index("id: selection") < workflow.index("uses: actions/setup-python")


def test_selector_failure_keeps_safe_receipt_and_no_secondary_artifact_error(tmp_path):
    git, _ = component_repo(tmp_path)
    base = git("rev-parse", "HEAD")
    bad = tmp_path / "apps/unreviewed/tests/test_new.py"
    bad.parent.mkdir(parents=True)
    bad.write_text("def test_new(): pass\n")
    git("add", ".")
    git("commit", "-qm", "unknown scope")
    head = git("rev-parse", "HEAD")
    output = tmp_path / "pr-selection.json"
    result = subprocess.run(
        [
            sys.executable,
            "tools/ci/pr_selection.py",
            "--base",
            base,
            "--head",
            head,
            "--output",
            str(output),
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode != 0 and not output.exists()
    receipt = json.loads(output.with_suffix(".blocked.json").read_text())
    assert receipt == dict(
        status="BLOCKED", source_sha=head, reason="unsupported_test_scope", scopes=[]
    )
    assert "pr-selection*.json" in (ROOT / ".github/workflows/runtime-api.yml").read_text()


def test_narrow_api_selection_does_not_collect_whole_api(monkeypatch, tmp_path):
    import pr_checks
    from test_pr_selection import passed_report

    manifest = selected("apps/api/tests/test_api.py")
    monkeypatch.setattr(pr_checks, "validate_selection", lambda *args: None)
    calls = []

    def invoke(root, output, config, targets, **kwargs):
        assert targets != ["apps/api/tests"]
        calls.append(targets)
        result = passed_report()
        result["wall_seconds"] = 0.01
        return result

    monkeypatch.setattr(pr_checks, "invoke", invoke)
    monkeypatch.setattr(pr_checks, "validate_artifacts", lambda *args: None)
    assert pr_checks.execute(ROOT, manifest, tmp_path)["status"] == "PASS"
    assert calls


def test_entire_api_selection_remains_blocked_before_any_collection(monkeypatch, tmp_path):
    import pr_checks

    manifest = selected("apps/api/tests/test_api.py")
    manifest["suites"]["api"]["targets"] = ["apps/api/tests"]
    monkeypatch.setattr(pr_checks, "validate_selection", lambda *args: None)
    monkeypatch.setattr(pr_checks, "invoke", lambda *a, **kw: pytest.fail("broad collection"))
    with pytest.raises(ValueError, match="entire_api_scope_requires_manual_full_regression"):
        pr_checks.execute(ROOT, manifest, tmp_path)
    result = json.loads((tmp_path / "pr-result.json").read_text())
    assert result["status"] == "BLOCKED" and result["full_regression_required"]


def test_forged_changed_files_cannot_pass_exact_source_validation(tmp_path):
    from copy import deepcopy

    git, folder = component_repo(tmp_path)
    base = git("rev-parse", "HEAD")
    path = folder / "test_transcription.py"
    path.write_text(path.read_text() + "\n# changed\n")
    git("add", ".")
    git("commit", "-qm", "source change")
    head = git("rev-parse", "HEAD")
    manifest = selection.build_selection(
        tmp_path, ["apps/stt/tests/test_transcription.py"], CONFIG, source_sha=head, merge_base=base
    )
    selection.validate_selection(manifest, tmp_path)
    forged = deepcopy(manifest)
    forged["changed_files"] = []
    forged["content_sha256"] = selection.digest(
        {k: v for k, v in forged.items() if k != "content_sha256"}
    )
    with pytest.raises(ValueError, match="selection_changed_files_mismatch"):
        selection.validate_selection(forged, tmp_path)
