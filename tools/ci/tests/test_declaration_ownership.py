"""CI-RISK-002: real source inventory and bounded positive/negative native gates."""

import io
import json
import subprocess
import sys
import tarfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pr_impact
import pr_selection
import qualification
from test_fixture_routing import scratch_repo

ROOT = Path(__file__).resolve().parents[3]
BASE = "262acb810f81cb75e6be0fa6d26361c7cdae0fdc"
ROLES = "fe5ec8466d2d6ca63a1fcb69483043aa0bbc3869"
CONFIG = json.loads((ROOT / "tools/ci/pr_routes.json").read_text())


@pytest.fixture(scope="module")
def roles_tree(tmp_path_factory):
    path = tmp_path_factory.mktemp("actual-roles-subject")
    archive = subprocess.check_output(["git", "archive", ROLES], cwd=ROOT)
    with tarfile.open(fileobj=io.BytesIO(archive)) as stream:
        stream.extractall(path, filter="data")
    return path


def test_real_roles_diff_has_explained_bounded_owners(roles_tree, monkeypatch):
    native_blob = pr_impact.blob
    monkeypatch.setattr(pr_impact, "blob", lambda root, rev, path: native_blob(ROOT, rev, path))
    base, paths = pr_selection.git_changes(ROOT, BASE, ROLES)
    result = pr_selection.build_selection(
        roles_tree, paths, CONFIG, source_sha=ROLES, merge_base=base
    )
    assert len(paths) == 77
    assert result["blocked_reasons"] == []
    assert result["needs_database"] and result["full_regression_required"]
    chosen = {t for g in result["suites"].values() for t in g["targets"]}
    assert {
        "apps/api/tests/test_current_roles.py",
        "apps/api/tests/test_current_roles_postgres.py",
        "apps/api/tests/test_f04_postgres.py",
        "packages/domain/tests/test_canonical_lock_policy.py",
    } <= chosen
    assert not {"packages/parser", "packages/prompts", "packages/model_gateway"} & set(
        result["suites"]
    )
    assert "apps/api/tests" not in chosen and "packages/domain/tests" not in chosen
    assert all(result["target_reasons"][t] for t in chosen)
    assert len(chosen) == len(pr_selection.normalize(chosen))


def test_decorators_and_all_parameters_are_part_of_changed_unit():
    before = '@pytest.mark.parametrize("x", [1,2])\ndef test_x(x):\n assert x > 0\n'
    after = before.replace("[1,2]", "[1,2,3]")
    assert pr_impact.units(before)["test_x"] != pr_impact.units(after)["test_x"]
    assert pr_impact.ast_hash(before) != pr_impact.ast_hash(after)


def test_changed_native_test_selects_whole_function_not_siblings(tmp_path, monkeypatch):
    source = tmp_path / "apps/api/tests/test_many.py"
    source.parent.mkdir(parents=True)
    before = "def test_changed(x):\n assert x\ndef test_unrelated():\n assert True\n"
    after = before.replace("assert x", "assert x == 1")
    source.write_text(after)
    monkeypatch.setattr(pr_impact, "blob", lambda root, rev, path: before if rev == BASE else after)
    direct, _, errors = pr_impact.test_changes(
        tmp_path, BASE, ROLES, source.relative_to(tmp_path).as_posix(), {}
    )
    assert not errors
    assert direct == ["apps/api/tests/test_many.py::test_changed"]


def test_reviewed_helper_pair_never_authorizes_later_edits(monkeypatch, tmp_path):
    path = "apps/api/tests/helper.py"
    before, after = "def setup():\n return 1\n", "def setup():\n return 2\n"
    current = [after]
    monkeypatch.setattr(
        pr_impact, "blob", lambda root, rev, path: before if rev == BASE else current[0]
    )
    contracts = {
        path: dict(
            source_pair=[pr_impact.ast_hash(before), pr_impact.ast_hash(after)],
            components=["roles"],
        )
    }
    assert pr_impact.test_changes(tmp_path, BASE, ROLES, path, contracts) == ([], ["roles"], [])
    current[0] = "def setup():\n return secret_other_fixture()\n"
    assert (
        "unreviewed_shared_test_support:" + path
        in pr_impact.test_changes(tmp_path, BASE, ROLES, path, contracts)[2]
    )


@pytest.mark.parametrize("path", ["apps/api/tests/conftest.py", "tests/new_helper.py"])
def test_unknown_shared_fixture_is_blocked(path, monkeypatch, tmp_path):
    monkeypatch.setattr(
        pr_impact,
        "blob",
        lambda root, rev, path: "" if rev == BASE else "def setup():\n return 1\n",
    )
    assert pr_impact.test_changes(tmp_path, BASE, ROLES, path, {})[2]


@pytest.mark.parametrize("path", ["apps/api/src/new_unowned.py", "data/unknown/value.txt"])
def test_unknown_executable_and_resource_fail_closed(path):
    m = pr_selection.build_selection(ROOT, [path], CONFIG, source_sha=ROLES, merge_base=BASE)
    assert m["blocked_reasons"] == ["unowned_executable_or_resource:" + path]


def test_ci_only_and_web_do_not_pull_backend():
    m = pr_selection.build_selection(
        ROOT, ["tools/ci/pr_checks.py"], CONFIG, source_sha=ROLES, merge_base=BASE
    )
    assert set(m["suites"]) == {"ci"} and not m["needs_database"]
    m = pr_selection.build_selection(
        ROOT, ["apps/web/src/new.tsx"], CONFIG, source_sha=ROLES, merge_base=BASE
    )
    assert not m["suites"] and not m["relevant"]


def test_shared_api_unowned_declaration_does_not_fall_back_to_all_api(monkeypatch):
    monkeypatch.setattr(
        pr_impact,
        "blob",
        lambda root, rev, path: "" if rev == BASE else "class CompletelyNewDTO:\n pass\n",
    )
    m = pr_selection.build_selection(
        ROOT, ["apps/api/src/jewelai_api/schemas.py"], CONFIG, source_sha=ROLES, merge_base=BASE
    )
    assert any("unowned_declaration:" in x for x in m["blocked_reasons"])
    assert "apps/api/tests" not in {t for g in m["suites"].values() for t in g["targets"]}


@pytest.mark.parametrize("value,expected", [("approved\n", "PASS"), ("broken", "FAIL")])
def test_complete_owned_resource_actual_native_gate(tmp_path, value, expected):
    config, git = scratch_repo(tmp_path, owned=True)
    scope = "apps/api/tests/owned"
    config.update(version=2, isolated_components={})
    config["ownership"] = dict(
        components={
            c: dict(tests=[scope], evidence="Complete synthetic owning namespace")
            for c in ("owned", "state_safety")
        },
        sources=[],
        resources=[dict(path=scope + "/*txt", components=["owned"])],
        test_support={},
    )
    (tmp_path / "tools/ci/pr_routes.json").write_text(json.dumps(config))
    git("add", ".")
    git("commit", "-qm", "v2 complete resource ownership")
    base = git("rev-parse", "HEAD")
    resource = scope + "/expected_value.txt"
    (tmp_path / resource).write_text(value)
    git("add", resource)
    git("commit", "-qm", "resource change")
    head = git("rev-parse", "HEAD")
    m = pr_selection.build_selection(tmp_path, [resource], config, source_sha=head, merge_base=base)
    manifest = tmp_path / "selection.json"
    manifest.write_text(json.dumps(m))
    out = tmp_path / "result"
    result = subprocess.run(
        [
            sys.executable,
            "tools/ci/pr_checks.py",
            "--manifest",
            str(manifest),
            "--output",
            str(out),
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=30,
    )
    receipt = json.loads((out / "pr-result.json").read_text())
    assert receipt["status"] == expected
    assert receipt["release_qualification"] == "NOT_QUALIFIED"
    assert result.returncode == (0 if expected == "PASS" else 1)
    assert "Risk-based PR gate" in (out / "summary.md").read_text()


def test_required_check_and_pg_safety_are_not_rewritten():
    runtime = (ROOT / ".github/workflows/runtime-api.yml").read_text()
    assert "name: Runtime API\n" in runtime and "  runtime:\n" in runtime
    assert "cancel-in-progress: ${{ github.event_name == 'pull_request' }}" in runtime
    assert runtime.index("verified_ci_postgres()") < runtime.index("alembic -c")
    assert "continue-on-error" not in runtime
    guard = (ROOT / "apps/api/tests/disposable_postgres.py").read_text()
    original = subprocess.check_output(
        ["git", "show", BASE + ":apps/api/tests/disposable_postgres.py"], cwd=ROOT, text=True
    )
    assert guard == original


@pytest.mark.parametrize(
    "path,owner,excluded",
    [
        ("packages/parser/src/jewelai_parser/full_message.py", "parser", "packages/model_gateway"),
        ("packages/domain/src/jewelai_domain/models.py", "canonical", "packages/model_gateway"),
        (
            "packages/model_gateway_openai/src/jewelai_model_gateway_openai/adapters.py",
            "model_gateway_openai",
            "packages/parser",
        ),
        ("workers/generation/src/jewelai_generation/worker.py", "worker", "packages/parser"),
        ("apps/stt/src/jewelai_stt/app.py", "apps/stt", "api"),
    ],
)
def test_representative_native_component_owners(monkeypatch, path, owner, excluded):
    monkeypatch.setattr(
        pr_impact,
        "blob",
        lambda root, rev, path: "" if rev == BASE else "def changed():\n return 1\n",
    )
    m = pr_selection.build_selection(ROOT, [path], CONFIG, source_sha=ROLES, merge_base=BASE)
    assert not m["blocked_reasons"]
    assert owner in m["buckets"]
    assert excluded not in m["suites"]


def test_changed_parametrization_executes_every_native_case(tmp_path):
    config, git = scratch_repo(tmp_path, owned=True)
    config.update(version=2, isolated_components={})
    config["ownership"] = dict(components={}, sources=[], resources=[], test_support={})
    (tmp_path / "tools/ci/pr_routes.json").write_text(json.dumps(config))
    path = "apps/api/tests/owned/test_parameters.py"
    original = (
        'import pytest\n@pytest.mark.parametrize("number", [1,2])\n'
        "def test_numbers(number):\n assert number > 0\n"
        'def test_unrelated():\n assert False, "not an affected case"\n'
    )
    (tmp_path / path).write_text(original)
    git("add", ".")
    git("commit", "-qm", "parameter baseline")
    base = git("rev-parse", "HEAD")
    (tmp_path / path).write_text(original.replace("[1,2]", "[1,2,3]"))
    git("add", path)
    git("commit", "-qm", "third parameter")
    head = git("rev-parse", "HEAD")
    manifest = pr_selection.build_selection(
        tmp_path, [path], config, source_sha=head, merge_base=base
    )
    assert manifest["suites"]["api"]["targets"] == [path + "::test_numbers"]
    source = tmp_path / "plan.json"
    source.write_text(json.dumps(manifest))
    output = tmp_path / "results"
    child = subprocess.run(
        [
            sys.executable,
            "tools/ci/pr_checks.py",
            "--manifest",
            str(source),
            "--output",
            str(output),
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=30,
    )
    result = json.loads((output / "pr-result.json").read_text())
    assert child.returncode == 0 and result["status"] == "PASS"
    assert result["groups"]["api"]["selected"] == 3


def test_release_evidence_discovery_is_exact_and_fail_closed(monkeypatch):
    good = dict(
        id=123,
        head_sha=ROLES,
        event="workflow_dispatch",
        status="completed",
        conclusion="success",
        path=qualification.WORKFLOW,
        repository=dict(full_name=qualification.REPOSITORY),
        run_attempt=1,
    )
    wrong = {**good, "head_sha": BASE}
    monkeypatch.setattr(
        qualification, "github_json", lambda path: dict(workflow_runs=[wrong, good])
    )
    assert qualification.latest_metadata(ROLES) == good
    monkeypatch.setattr(qualification, "github_json", lambda path: dict(workflow_runs=[wrong]))
    with pytest.raises(ValueError, match="not_available_for_exact_sha"):
        qualification.latest_metadata(ROLES)


def test_proposed_release_condition_is_reviewable_but_not_activated():
    patch = ROOT / "tools/ci/release-gate.proposed.patch"
    text = patch.read_text()
    assert "+          python tools/ci/qualification.py check" in text
    assert "Require validated exact-SHA release evidence before GCP access" in text
    assert "deploy-production" not in text
    subprocess.run(
        ["git", "apply", "--check", str(patch)], cwd=ROOT, check=True, capture_output=True
    )
    # This is the explicit Owner deployment-rule gate; do not silently claim enforcement.
    workflow = (ROOT / ".github/workflows/deploy-preprod.yml").read_text()
    assert "Locate exact-release-SHA Full qualification" not in workflow
