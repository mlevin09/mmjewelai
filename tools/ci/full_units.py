"""Existing full package selections with strict native outcome accounting."""

import argparse
import json
import re
from pathlib import Path

# This is the existing workflow's suite list, not individual test classification.
SCOPES = {
    **{
        f"packages/{name}": dict(
            config=f"packages/{name}/pyproject.toml", targets=[f"packages/{name}/tests"]
        )
        for name in [
            "domain",
            "auth",
            "auth_oidc",
            "auth_identity_platform",
            "generation_queue",
            "generation_queue_gcp",
            "parser",
            "text_understanding_google",
            "prompts",
            "model_gateway",
            "model_gateway_google",
            "model_gateway_openai",
            "assets",
            "assets_gcs",
        ]
    },
    "workers/generation": dict(
        config="workers/generation/pyproject.toml", targets=["workers/generation/tests"]
    ),
    "root_pipeline": dict(
        config="workers/generation/pyproject.toml",
        targets=["tests/test_openai_generation_pipeline.py"],
    ),
    "root": dict(
        config="pyproject.toml",
        targets=[
            "tests/test_knowledge_library_behavioral_regression.py",
            "tests/test_knowledge_library_production_catalog.py",
            "tests/test_knowledge_library_three_stone_vertical_slice.py",
        ],
    ),
    "ci": dict(config="apps/api/pyproject.toml", targets=["tools/ci/tests"]),
}

# Full qualification must not silently omit a registered app after it is merged.
_root = Path(__file__).resolve().parents[2]
_config = json.loads((_root / "tools/ci/pr_routes.json").read_text())
for _app in _config.get("isolated_components", {}):
    if (_root / _app / "pyproject.toml").is_file() and list(
        (_root / _app / "tests").rglob("test_*.py")
    ):
        SCOPES[_app] = dict(config=_app + "/pyproject.toml", targets=[_app + "/tests"])


def audit_inventory(root):
    expected = {t for group in SCOPES.values() for t in group["targets"]}
    actual = {
        p.relative_to(root).as_posix()
        for area in ("packages", "workers")
        for p in (root / area).glob("*/tests")
        if list(p.rglob("test_*.py"))
    }
    actual.update(p.relative_to(root).as_posix() for p in (root / "tests").glob("test_*.py"))
    actual.update(
        p.relative_to(root).as_posix()
        for p in (root / "apps").glob("*/tests")
        if p.parent.name != "api" and list(p.rglob("test_*.py"))
    )
    actual.add("tools/ci/tests")
    if actual != expected:
        raise ValueError("full_unit_scope_drift_requires_explicit_configuration")


def check_proof(proof):
    if set(proof) != set(SCOPES):
        raise ValueError("missing_full_unit_suite")
    for name, group in SCOPES.items():
        row = proof[name]
        if (
            row.get("targets") != group["targets"]
            or not row.get("case_ids")
            or len(row["case_ids"]) != len(set(row["case_ids"]))
            or any(not re.fullmatch("[0-9a-f]{64}", case) for case in row["case_ids"])
        ):
            raise ValueError("incomplete_full_unit_suite")
    return proof


def covers(proof, selected):
    check_proof(proof)
    scopes = [t for group in SCOPES.values() for t in group["targets"]] + ["apps/api/tests"]
    return all(
        any(
            t == scope or t.startswith(scope + "/") or t.startswith(scope + "::")
            for scope in scopes
        )
        for group in selected.values()
        for t in group["targets"]
    )


def main():
    from api_partitions import validate_artifacts
    from pr_checks import invoke, verify_execution

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    parser.add_argument("--proof", required=True)
    args = parser.parse_args()
    root = Path.cwd()
    audit_inventory(root)
    output = Path(args.output)
    proof = {}
    for name, group in SCOPES.items():
        folder = output / name.replace("/", "_")
        report = invoke(root, folder, group["config"], group["targets"], timeout=600)
        verify_execution(report, report["collection_ids"])
        validate_artifacts(folder, report)
        proof[name] = dict(targets=group["targets"], case_ids=report["collection_ids"])
    check_proof(proof)
    path = Path(args.proof)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(proof, indent=2))
    print("full_unit_scopes: PASS")


if __name__ == "__main__":
    main()
