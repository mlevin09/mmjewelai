"""Complete scope coverage is independent of a consumer's Python reader syntax."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from test_fixture_routing import scratch_repo
from test_pr_selection import selected, selection, targets


@pytest.mark.parametrize("syntax", ["path_variable", "open_alias"])
def test_complete_scope_executes_indirect_reader(tmp_path, syntax):
    config, git = scratch_repo(tmp_path, owned=True)
    scope = "apps/api/tests/owned"
    folder = tmp_path / scope
    reader = (
        '    fixture = Path(__file__).with_name("expected_value.txt")\n'
        "    actual = fixture.read_text().strip()\n"
        if syntax == "path_variable"
        else "    read = open\n"
        '    with read(Path(__file__).with_name("expected_value.txt")) as stream:\n'
        "        actual = stream.read().strip()\n"
    )
    (folder / "test_opaque.py").write_text(
        "from pathlib import Path\ndef test_contract():\n"
        + reader
        + '    assert actual == "approved"\n'
    )
    # A literal reader that accepts either content must never stand in for opaque.
    (folder / "test_consumer.py").write_text(
        "from pathlib import Path\ndef test_encoding():\n"
        '    assert Path(__file__).with_name("expected_value.txt").read_text().isascii()\n'
    )
    git("add", ".")
    git("commit", "-qm", "complete independent owning namespace")
    base = git("rev-parse", "HEAD")
    results = []
    for label, value in [("compatible", "approved\n"), ("broken", "broken")]:
        (folder / "expected_value.txt").write_text(value)
        git("add", scope + "/expected_value.txt")
        git("commit", "-qm", label)
        head = git("rev-parse", "HEAD")
        merge, changed = selection.git_changes(tmp_path, base, head)
        manifest = selection.build_selection(
            tmp_path, changed, config, source_sha=head, merge_base=merge
        )
        path = tmp_path / (label + "-selection.json")
        path.write_text(json.dumps(manifest))
        output = tmp_path / (label + "-gate")
        child = subprocess.run(
            [
                sys.executable,
                "tools/ci/pr_checks.py",
                "--manifest",
                str(path),
                "--output",
                str(output),
            ],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            timeout=30,
        )
        result = json.loads((output / "pr-result.json").read_text())
        execution = json.loads((output / "api-execution/timings.json").read_text())
        assert result["groups"]["api"]["selected"] == 3
        assert scope in targets(manifest) and not manifest["blocked_reasons"]
        opaque = next(c for c in execution["testcases"] if c["module"].endswith("test_opaque.py"))
        assert opaque["outcome"] == ("passed" if label == "compatible" else "failed")
        assert child.returncode == (0 if label == "compatible" else 1)
        results.append(
            dict(
                label=label,
                manifest=manifest,
                result=result,
                execution=execution,
                gate_exit=child.returncode,
            )
        )
    if destination := os.getenv("FIXTURE_SCOPE_EVIDENCE_DIR"):
        p = Path(destination)
        p.mkdir(parents=True, exist_ok=True)
        (p / (syntax + ".json")).write_text(json.dumps(results, indent=2))


@pytest.mark.parametrize(
    "scope", ["apps/api/tests", "apps/api/tests/test_consumer.py", "apps/api/tests/missing"]
)
def test_invalid_or_full_api_mapping_cannot_clear_gate(tmp_path, scope):
    config, _ = scratch_repo(tmp_path)
    config["fixture_scopes"] = [
        dict(resources="apps/api/tests", tests=scope, evidence="synthetic invalid mapping")
    ]
    with pytest.raises(ValueError, match="fixture_scope_not_bounded"):
        selection.build_selection(
            tmp_path,
            ["apps/api/tests/expected_value.txt"],
            config,
            source_sha="a" * 40,
            merge_base="b" * 40,
        )


def test_known_reader_does_not_qualify_unowned_resource(tmp_path):
    config, _ = scratch_repo(tmp_path)
    result = selection.build_selection(
        tmp_path,
        ["apps/api/tests/expected_value.txt"],
        config,
        source_sha="a" * 40,
        merge_base="b" * 40,
    )
    assert result["blocked_reasons"] == ["unmapped_fixture_data"]
    assert "apps/api/tests" not in targets(result)
    assert "apps/api/tests/test_consumer.py" not in targets(result)


@pytest.mark.parametrize(
    "path",
    [
        "data/prompts/source.json",
        "packages/prompts/src/templates/source.txt",
        "specs/prompts/fixtures/input.md",
    ],
)
def test_runtime_data_cannot_pass_on_partial_component_routes(path):
    result = selected(path)
    assert result["relevant"] and not result["docs_only"]
    assert "unmapped_fixture_data" in result["blocked_reasons"]


@pytest.mark.parametrize("path", ["README.md", "apps/api/tests/owned/fixtures/example.py"])
def test_explicit_resource_ownership_precedes_extension_and_docs(tmp_path, path):
    config, _ = scratch_repo(tmp_path, owned=True)
    config["fixture_scopes"] = [
        dict(
            resources=path,
            tests="apps/api/tests/owned",
            evidence="Self-contained synthetic contract scope, including this declared input.",
        )
    ]
    result = selection.build_selection(
        tmp_path, [path], config, source_sha="a" * 40, merge_base="b" * 40
    )
    assert not result["docs_only"]
    assert "apps/api/tests/owned" in targets(result)
    assert not result["blocked_reasons"]


def test_unowned_python_fixture_is_not_treated_as_helper_code():
    result = selected("apps/api/tests/fixtures/example.py")
    assert "unmapped_fixture_data" in result["blocked_reasons"]
