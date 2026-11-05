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


def fixture_consumers(root, path):
    """Keep confirmed tests and unresolved reader modules independently."""
    folder = test_root(path)
    if folder is None:
        return dict(confirmed=[], unresolved=[])
    resource = Path(path)
    references = {path}
    relative = resource.relative_to(folder).as_posix()
    if "/" in relative:
        references.add(relative)
    # A basename alone cannot resolve two different resources in the same suite.
    same_names = {p.resolve() for p in (root / folder).rglob(resource.name)}
    same_names.add((root / path).resolve())  # Also retain deleted resources.
    if len(same_names) == 1:
        references.add(resource.name)
    readers, unresolved = set(), set()
    for source in (root / folder).rglob("*.py"):
        if not source.resolve().is_relative_to(root.resolve()):
            raise ValueError("external_fixture_dependency")
        tree = ast.parse(source.read_text())
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            operation = getattr(node.func, "attr", getattr(node.func, "id", None))
            if operation not in {"open", "read_text", "read_bytes"}:
                continue
            literals = {
                value.value.replace("\\", "/")
                for value in ast.walk(node)
                if isinstance(value, ast.Constant) and isinstance(value.value, str)
            }
            owner = source.relative_to(root).as_posix()
            if literals & references:
                readers.add(owner)
            # A full-path match elsewhere cannot discharge this possible reader.
            if len(same_names) > 1 and resource.name in literals:
                unresolved.add(owner)
    return dict(
        confirmed=sorted(
            {p for p in readers if Path(p).name.startswith("test_")}
            | set(dependent_tests(root, readers))
        ),
        unresolved=sorted(unresolved),
    )


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
        is_fixture = test_root(path) is not None and not path.endswith(".py")
        consumers, unresolved = [], []
        if is_fixture:
            dependency = fixture_consumers(root, path)
            fixture_dependencies[path] = dependency
            consumers, unresolved = dependency["confirmed"], dependency["unresolved"]
        if not consumers and not unresolved and is_documentation(path):
            continue
        for consumer in consumers:
            add(consumer, "fixture_file_dependency")
        docs = False
        if any(path.startswith(p) for p in config["delegated_prefixes"]):
            continue
        relevant = True
        is_test = (
            test_root(path) is not None
            and Path(path).name.startswith("test_")
            and path.endswith(".py")
        )
        if is_test and (root / path).exists():
            add(path, "new_or_modified_test_file")
        matched = bool(consumers)
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
            full.append("shared_authority_schema_or_migration")
            buckets.update({"continuation", "evidence", "persistence"})
        if path in {"apps/api/src/jewelai_api/app.py", "apps/api/src/jewelai_api/services.py"}:
            full.append("shared_api_dispatch")
            buckets.update({"authorization", "persistence"})
        if is_fixture and (not consumers or unresolved):
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
