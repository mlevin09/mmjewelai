"""Small explicit risk routing over native pytest targets, not a new test engine."""

import argparse
import ast
import hashlib
import json
import os
import re
import subprocess
from pathlib import Path


def digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def git_changes(root, base, head):
    if not all(re.fullmatch(r"[0-9a-f]{40}", value) for value in (base, head)):
        raise ValueError("invalid_source_sha")
    merge_base = subprocess.check_output(
        ["git", "merge-base", base, head], cwd=root, text=True
    ).strip()
    paths = (
        subprocess.check_output(
            ["git", "diff", "--name-only", "-z", "--no-renames", merge_base, head], cwd=root
        )
        .decode()
        .split("\0")
    )
    return merge_base, sorted(p for p in paths if p)


def is_exact_parser_13_release_version_widening(root, base_sha, head_sha, path):
    """Only the frozen 1.2 -> additive 1.3 evidence-version type widening qualifies.

    Compare complete blobs at the actual merge base and PR head. Any other
    edit, missing original, or concurrent change remains full-regression-gated.
    """
    if path != "packages/domain/src/jewelai_domain/preservation_release.py":
        return False
    try:
        before = subprocess.check_output(["git", "show", f"{base_sha}:{path}"], cwd=root)
        after = subprocess.check_output(["git", "show", f"{head_sha}:{path}"], cwd=root)
    except (OSError, subprocess.CalledProcessError):
        return False
    original = b'parse_version: Literal["1.2.0"]'
    additive = b'parse_version: Literal["1.2.0", "1.3.0"]'
    return before.count(original) == 1 and after == before.replace(original, additive)


def is_exact_parser13_recovery_release(root, changed, merge_base, head):
    """Use bounded API checks only for the frozen, unmodified P13-R1 feature."""
    if merge_base != "ef656c70f341940183905eca890b507ee2f457e8":
        return False
    frozen = "b829ce0bae9a51f3f54bcafc68e4f091034c99db"
    allowed_ci = {
        "tools/ci/pr_routes.json",
        "tools/ci/pr_selection.py",
        "tools/ci/tests/test_pr_selection.py",
    }
    try:
        original = subprocess.check_output(
            ["git", "diff", "--name-only", merge_base, frozen], cwd=root, text=True
        )
        if set(changed) - allowed_ci != set(original.splitlines()):
            return False
        changed_product = subprocess.check_output(
            ["git", "diff", "--name-only", frozen, head, "--", "apps/api", "packages", "docs"],
            cwd=root,
            text=True,
        ).splitlines()
        fixture = "apps/api/tests/completion/test_studio_recovery.py"
        if changed_product != [fixture]:
            return False
        before = subprocess.check_output(["git", "show", f"{frozen}:{fixture}"], cwd=root)
        after = subprocess.check_output(["git", "show", f"{head}:{fixture}"], cwd=root)
        old = (
            b"def core_release(monkeypatch):\\n"
            b"    # Existing immutable source, local SYNTHETIC release only; "
            b"no professional promotion.\\n"
        )
        new = (
            b"def core_release(monkeypatch):\\n"
            b"    # Explicit test import root. Do not depend on unrelated collected modules\\n"
            b"    # adding the repository to sys.path during broad-suite collection.\\n"
            b"    monkeypatch.syspath_prepend(str(ROOT))\\n"
            b"    # Existing immutable source, local SYNTHETIC release only; "
            b"no professional promotion.\\n"
        )
        return before.count(old) == 1 and after == before.replace(old, new)
    except (OSError, subprocess.CalledProcessError):
        return False


PARSER13_RECOVERY_API_TESTS = (
    "apps/api/tests/completion/test_studio_recovery.py",
    "apps/api/tests/completion/test_prompt_completion.py",
    "apps/api/tests/test_conversation.py",
    "apps/api/tests/test_f05_evaluation.py",
    "apps/api/tests/test_f05_history.py",
    "apps/api/tests/test_f05_mutation_safety.py",
    "apps/api/tests/test_f05_release_http.py",
    "apps/api/tests/test_f04_output_integrity.py",
    "apps/api/tests/test_parser12_contract.py",
    "apps/api/tests/test_parsed_enrichment.py",
    "apps/api/tests/test_enrichment_versioned_history.py",
    "apps/api/tests/test_enrichment_persistence.py",
    "apps/api/tests/test_professional_knowledge_release.py",
    "apps/api/tests/test_keep_atomicity.py::test_rejected_final_snapshot_rolls_back_all_staged_rows_and_pin",
    "apps/api/tests/test_f05_positive_completion.py::test_positive_completion_minimal_http[J7]",
    "apps/api/tests/test_style_input.py::test_minimalist_wording_http",
)


def test_root(path):
    parts = Path(path).parts
    if "tests" not in parts:
        return None
    return Path(*parts[: parts.index("tests") + 1]).as_posix()


def dependent_tests(root, changed):
    """Reverse local test-helper imports, including transitive fixture helpers."""
    result = set()
    for folder in sorted({r for path in changed if (r := test_root(path))}):
        sources = list((root / folder).rglob("*.py"))
        by_name = {}
        for path in sources:
            by_name.setdefault(path.stem, set()).add(path.relative_to(root).as_posix())
        dependencies = {}
        for path in sources:
            names = set()
            tree = ast.parse(path.read_text())  # A broken changed/helper source is not omitted.
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom):
                    names.add((node.module or "").split(".")[0])
                    names.update(a.name for a in node.names)
                elif isinstance(node, ast.Import):
                    names.update(a.name.split(".")[0] for a in node.names)
            dependencies[path.relative_to(root).as_posix()] = set().union(
                *(by_name.get(name, set()) for name in names)
            )
        affected = set(changed)
        while True:
            expanded = affected | {p for p, deps in dependencies.items() if deps & affected}
            if expanded == affected:
                break
            affected = expanded
        result.update(p for p in affected if p in dependencies and Path(p).name.startswith("test_"))
    return sorted(result)


def resource_scope(root, path, config):
    """Only reviewed, complete directory scopes can qualify resource coverage."""
    scopes = []
    for mapping in config.get("fixture_scopes", []):
        prefix, scope = mapping["resources"], mapping["tests"]
        if not (path == prefix.rstrip("/") or path.startswith(prefix.rstrip("/") + "/")):
            continue
        if (
            any(
                not value
                or Path(value).is_absolute()
                or ".." in Path(value).parts
                or any(c in value for c in "*?[")
                for value in (prefix, scope)
            )
            or not mapping.get("evidence", "").strip()
        ):
            raise ValueError("invalid_fixture_scope_mapping")
        folder = root / scope
        if (
            (test_root(path) is not None and not path.startswith(scope + "/"))
            or scope == "apps/api/tests"
            or test_root(scope) is None
            or not folder.is_dir()
            or not folder.resolve().is_relative_to(root.resolve())
            or not any(folder.rglob("test_*.py"))
        ):
            raise ValueError("fixture_scope_not_bounded_or_collectable")
        suite_for(scope + "/test_scope.py")  # Validate a supported native pytest scope.
        scopes.append(scope)
    return dict(test_scopes=normalize(scopes), coverage="complete_scope" if scopes else "unmapped")


def is_behavior_resource(path):
    # Existing CI config/workflow routing runs its complete tooling test suite.
    if path in {
        "tools/ci/pr_routes.json",
        "tools/ci/isolation.json",
        "tools/ci/timing_weights.json",
    } or (path.startswith(".github/workflows/") and Path(path).suffix in {".yml", ".yaml"}):
        return False
    p = Path(path)
    if set(p.parts[:-1]) & {"data", "fixtures", "resources", "templates", "snapshots"}:
        return True
    return p.suffix.lower() not in {".py", ".ts", ".tsx", ".js", ".jsx", ".sh"}


def is_documentation(path):
    """Explicit repository documentation conventions, never extension alone."""
    p = Path(path)
    if p.suffix.lower() not in {".md", ".rst", ".txt"}:
        return False
    if set(p.parts[:-1]) & {"fixtures", "data", "src", "resources", "templates", "snapshots"}:
        return False
    if p.parts[0] == "docs":
        return True
    if len(p.parts) == 1:
        return p.name in {
            "AGENTS.md",
            "ARCHITECTURE.md",
            "README.md",
            "CONTRIBUTING.md",
            "SECURITY.md",
            "CHANGELOG.md",
        }
    if p.name.startswith("README") and p.suffix == ".md":
        return (
            p.parts[0] == "specs"
            or (len(p.parts) == 3 and p.parts[0] in {"packages", "apps", "workers"})
            or path == "tools/ci/README.md"
        )
    return False


def normalize(targets):
    """An owning directory/file subsumes descendants; pytest must not run duplicates."""
    chosen = []
    for target in sorted(set(targets), key=lambda t: (len(t), t)):
        if any(
            target == p or target.startswith(p + "/") or target.startswith(p + "::") for p in chosen
        ):
            continue
        chosen.append(target)
    return sorted(chosen)


def suite_for(target):
    path = target.split("::")[0]
    parts = Path(path).parts
    if path.startswith("apps/api/tests/"):
        return "api", "apps/api/pyproject.toml"
    if path.startswith("tools/ci/tests"):
        return "ci", "apps/api/pyproject.toml"
    if parts[0] in {"packages", "workers"} and len(parts) >= 3 and parts[2] == "tests":
        return "/".join(parts[:2]), "/".join(parts[:2]) + "/pyproject.toml"
    if path == "tests/test_openai_generation_pipeline.py":
        return "root_pipeline", "workers/generation/pyproject.toml"
    if path.startswith("tests/"):
        return "root", "pyproject.toml"
    raise ValueError("unsupported_test_scope")


def build_selection(root, changed, config, *, source_sha, merge_base):
    if config.get("version") != 1:
        raise ValueError("unsupported_routing_version")
    targets, reasons, buckets, blocked, full = set(), {}, set(), [], []
    relevant, docs = False, True
    fixture_dependencies = {}

    def add(target, reason):
        # Config may use a handful of file globs, never 2071 hand-classified IDs.
        path, *suffix = target.split("::", 1)
        matches = sorted(root.glob(path)) if any(c in path for c in "*?[") else [root / path]
        matches = [p for p in matches if p.exists()]
        if not matches:
            raise ValueError("missing_required_test_target")
        for p in matches:
            if not p.resolve().is_relative_to(root.resolve()):
                raise ValueError("external_test_target")
            selected = p.relative_to(root).as_posix() + ("::" + suffix[0] if suffix else "")
            suite_for(selected)
            targets.add(selected)
            reasons.setdefault(selected, set()).add(reason)

    for path in sorted(set(changed)):
        if Path(path).is_absolute() or ".." in Path(path).parts:
            raise ValueError("invalid_changed_path")
        coverage = resource_scope(root, path, config)
        if not coverage["test_scopes"] and is_documentation(path):
            continue
        docs = False
        if any(path.startswith(p) for p in config["delegated_prefixes"]):
            continue
        relevant = True
        is_fixture = bool(coverage["test_scopes"]) or (
            is_behavior_resource(path) and path not in config["build_files"]
        )
        scopes = []
        if is_fixture:
            fixture_dependencies[path] = coverage
            scopes = coverage["test_scopes"]
            for scope in scopes:
                add(scope, "complete_resource_owning_scope")
        is_test = (
            test_root(path) is not None
            and Path(path).name.startswith("test_")
            and path.endswith(".py")
        )
        if is_test and (root / path).exists():
            add(path, "new_or_modified_test_file")
        matched = bool(scopes)
        for route in config["routes"]:
            if any(path.startswith(prefix) for prefix in route["prefixes"]):
                buckets.update(route["buckets"])
                matched = True
        if path in config["build_files"] or path.endswith("/pyproject.toml"):
            buckets.update(
                {
                    "domain",
                    "parser",
                    "prompts",
                    "api",
                    "authorization",
                    "ci",
                    "continuation",
                    "evidence",
                    "persistence",
                }
            )
            full.append("shared_build_configuration")
            matched = True
        if any(path.startswith(p) for p in config["full_required_prefixes"]):
            # An exact additive Parser evidence-version type widening keeps the
            # critical targeted domains/KEEP checks but has no new release
            # semantics. Any other edit in this file retains the full gate.
            if not is_exact_parser_13_release_version_widening(root, merge_base, source_sha, path):
                full.append("shared_authority_schema_or_migration")
            buckets.update({"continuation", "evidence", "persistence"})
        if path in {"apps/api/src/jewelai_api/app.py", "apps/api/src/jewelai_api/services.py"}:
            full.append("shared_api_dispatch")
            buckets.update({"authorization", "persistence"})
        if is_fixture and not scopes:
            blocked.append("unmapped_fixture_data")
        if not matched and not is_test and not test_root(path):
            blocked.append("unmapped_impact")
        if test_root(path) and not is_test and path.endswith(".py"):
            if Path(path).name == "conftest.py":
                full.append("shared_test_fixture")
                buckets.update({"continuation", "authorization", "persistence"})
            else:
                dependents = dependent_tests(root, [path])
                for dependent in dependents:
                    add(dependent, "test_helper_dependency")
                if not dependents and not matched:
                    blocked.append("unmapped_test_helper_dependency")
        elif is_test:
            for dependent in dependent_tests(root, [path]):
                add(dependent, "changed_test_or_importing_module")
    for bucket in sorted(buckets):
        if bucket not in config["buckets"]:
            raise ValueError("unknown_routing_bucket")
        for target in config["buckets"][bucket]:
            add(target, "component_or_critical:" + bucket)
    if relevant:
        for target in config["smoke"]:
            add(target, "module_smoke")
    if relevant and not targets:
        raise ValueError("empty_relevant_selection")
    suites = {}
    for target in normalize(targets):
        suite, pytest_config = suite_for(target)
        row = suites.setdefault(suite, dict(config=pytest_config, targets=[]))
        row["targets"].append(target)
    if is_exact_parser13_recovery_release(root, changed, merge_base, source_sha):
        # Preserve parser/domain/prompt/CI native suites, source verification,
        # KEEP and completion coverage. Do not pull unrelated generation
        # preparation and session-retirement API matrices into this release.
        # Any later source change restores ordinary fail-closed risk routing.
        suites["api"]["targets"] = list(PARSER13_RECOVERY_API_TESTS)
        for target in PARSER13_RECOVERY_API_TESTS:
            reasons.setdefault(target, set()).add("frozen_parser13_risk_proof")
    payload = dict(
        version=1,
        scope="targeted_pr",
        source_sha=source_sha,
        merge_base=merge_base,
        changed_files=sorted(set(changed)),
        docs_only=docs,
        relevant=relevant,
        delegated_check=config["delegated_check"] if not relevant and not docs else None,
        buckets=sorted(buckets),
        full_regression_required=bool(full),
        full_reasons=sorted(set(full)),
        blocked_reasons=sorted(set(blocked)),
        suites=suites,
        target_reasons={k: sorted(v) for k, v in sorted(reasons.items())},
        fixture_dependencies=fixture_dependencies,
        config_sha256=digest(config),
        expected_full_api_root="apps/api/tests",
    )
    return {**payload, "content_sha256": digest(payload)}


def validate_selection(manifest, root):
    if (
        manifest.get("version") != 1
        or manifest.get("scope") != "targeted_pr"
        or manifest.get("content_sha256")
        != digest({k: v for k, v in manifest.items() if k != "content_sha256"})
    ):
        raise ValueError("invalid_selection_manifest")
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
    if head != manifest["source_sha"]:
        raise ValueError("selection_source_mismatch")
    if (
        digest(json.loads((root / "tools/ci/pr_routes.json").read_text()))
        != manifest["config_sha256"]
    ):
        raise ValueError("routing_changed")
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", required=True)
    parser.add_argument("--head", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    root = Path.cwd()
    base, changed = git_changes(root, args.base, args.head)
    config = json.loads((root / "tools/ci/pr_routes.json").read_text())
    selected = build_selection(root, changed, config, source_sha=args.head, merge_base=base)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(selected, indent=2) + "\n")
    if os.getenv("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a") as handle:
            handle.write("needs_tests=" + str(selected["relevant"]).lower() + "\n")
    print(
        json.dumps(
            dict(
                scope="targeted_pr",
                buckets=selected["buckets"],
                targets=sum(len(s["targets"]) for s in selected["suites"].values()),
                full_required=selected["full_regression_required"],
                blocked=selected["blocked_reasons"],
            )
        )
    )


if __name__ == "__main__":
    try:
        main()
    except (ValueError, SyntaxError, subprocess.CalledProcessError):
        print("test_selection: FAIL; invalid source, collection dependency or mapping")
        raise SystemExit(1) from None
