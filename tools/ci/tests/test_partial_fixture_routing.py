"""Mixed confirmed/unresolved fixture ownership must never become a green gate."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from test_fixture_routing import scratch_repo
from test_pr_selection import selection, targets


@pytest.mark.parametrize("scenario", ["mixed", "known_only", "multiple"])
def test_partial_fixture_dependencies_use_actual_cli_gate(tmp_path, scenario):
    config, git = scratch_repo(tmp_path)
    tests = tmp_path / "apps/api/tests"
    (tests / "test_consumer.py").unlink()
    (tests / "test_explicit.py").write_text(
        "from pathlib import Path\ndef test_encoding():\n"
        '    assert Path("apps/api/tests/expected_value.txt").read_text().isascii()\n'
    )
    if scenario != "known_only":
        (tests / "test_strict.py").write_text(
            "from pathlib import Path\ndef test_contract():\n"
            '    assert Path(__file__).with_name("expected_value.txt").read_text()'
            '.strip() == "approved"\n'
        )
    if scenario in {"mixed", "known_only"}:
        (tests / "other").mkdir()
        (tests / "other/expected_value.txt").write_text("other")
    git("add", ".")
    git("commit", "-qm", "synthetic consumer layout")
    base = git("rev-parse", "HEAD")
    # Known-only and multiple-consumer controls stay compatible. The exact mixed
    # reproduction changes only the fixture; encoding still passes, content fails.
    (tests / "expected_value.txt").write_text("broken" if scenario == "mixed" else "approved\n")
    git("add", "apps/api/tests/expected_value.txt")
    git("commit", "-qm", "fixture-only change")
    head = git("rev-parse", "HEAD")
    merge, changed = selection.git_changes(tmp_path, base, head)
    assert changed == ["apps/api/tests/expected_value.txt"]
    manifest = selection.build_selection(
        tmp_path, changed, config, source_sha=head, merge_base=merge
    )
    path = tmp_path / "selection.json"
    path.write_text(json.dumps(manifest))
    child = subprocess.run(
        [
            sys.executable,
            "tools/ci/pr_checks.py",
            "--manifest",
            str(path),
            "--output",
            str(tmp_path / "gate"),
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=30,
    )
    result = json.loads((tmp_path / "gate/pr-result.json").read_text())
    observed = dict(scenario=scenario, manifest=manifest, gate=result, gate_exit=child.returncode)
    if scenario == "mixed":
        # Both tests the old selector did choose still really pass; only the
        # independent strict reader fails. No mock replaces the actual executor.
        for label, names, expected in [
            ("selected", ["test_explicit.py", "test_smoke.py"], 0),
            ("strict", ["test_strict.py"], 1),
        ]:
            probe = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "pytest",
                    "-c",
                    "apps/api/pyproject.toml",
                    *[str(Path("apps/api/tests") / n) for n in names],
                    "-q",
                    "-p",
                    "no:cacheprovider",
                ],
                cwd=tmp_path,
                capture_output=True,
                text=True,
                timeout=15,
            )
            observed[label + "_exit"] = probe.returncode
            assert probe.returncode == expected
    if folder := os.getenv("PARTIAL_FIXTURE_EVIDENCE_DIR"):
        dest = Path(folder)
        dest.mkdir(parents=True, exist_ok=True)
        (dest / (scenario + ".json")).write_text(json.dumps(observed, indent=2))
    assert "apps/api/tests/test_explicit.py" in targets(manifest)
    assert "apps/api/tests/test_unrelated.py" not in targets(manifest)
    if scenario == "mixed":
        assert child.returncode != 0 and result["result"] == "failure"
        assert "unmapped_fixture_data" in manifest["blocked_reasons"]
        dependency = manifest["fixture_dependencies"][changed[0]]
        assert dependency["confirmed"] == ["apps/api/tests/test_explicit.py"]
        assert dependency["unresolved"] == ["apps/api/tests/test_strict.py"]
    else:
        assert child.returncode == 0 and result["result"] == "success"
        assert not manifest["blocked_reasons"]
        if scenario == "multiple":
            assert "apps/api/tests/test_strict.py" in targets(manifest)
            assert result["groups"]["api"]["selected"] == 3
