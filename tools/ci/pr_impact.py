"""Declaration ownership for the existing PR selector; no pytest execution or reader inference."""

import ast
import fnmatch
import hashlib
import json
import os
import subprocess
from pathlib import Path


def blob(root, revision, path):
    result = subprocess.run(
        ["git", "show", f"{revision}:{path}"], cwd=root, capture_output=True, text=True
    )
    if (
        result.returncode
        and subprocess.run(
            ["git", "cat-file", "-e", revision + "^{commit}"], cwd=root, capture_output=True
        ).returncode
    ):
        raise ValueError("impact_source_unavailable")
    return result.stdout if result.returncode == 0 else ""


def units(source):
    """Keep headers, imports and executable module statements; ignore only docstrings/comments.

    Class methods are separate units. Function bodies retain nested statements: a
    changed endpoint inside create_app also selects bootstrap/authentication checks.
    Decorators/defaults/annotations are included, so changed parametrization is not omitted.
    """
    tree = ast.parse(source)
    result = {}

    def visit(body, prefix=""):
        other = []
        for node in body:
            if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant):
                if isinstance(node.value.value, str):
                    continue
            if isinstance(node, ast.ClassDef):
                methods = [
                    n for n in node.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                ]
                node.body = [n for n in node.body if n not in methods]
                result[prefix + node.name] = ast.dump(node, include_attributes=False)
                visit(methods, prefix + node.name + ".")
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                result[prefix + node.name] = ast.dump(node, include_attributes=False)
            else:
                other.append(ast.dump(node, include_attributes=False))
        if other:
            result[prefix + "@module"] = json.dumps(other, separators=(",", ":"))

    visit(tree.body)
    return result


def changes(root, base, head, path):
    before, after = units(blob(root, base, path)), units(blob(root, head, path))
    return sorted(k for k in before.keys() | after.keys() if before.get(k) != after.get(k))


def ast_hash(source):
    return hashlib.sha256(json.dumps(units(source), sort_keys=True).encode()).hexdigest()


def test_changes(root, base, head, path, contracts, contract_components=()):
    """Whole parametrized functions, never guessed parameter subsets or file-import expansion.

    Shared fixture/helper changes need a reviewed *pair* of semantic source hashes and
    explicit contract coverage. Unknown helpers block; matching an import is not proof.
    New test modules are selected completely. Module constants/imports can affect every
    function and therefore require complete module coverage unless contract-reviewed.
    """
    before, after = blob(root, base, path), blob(root, head, path)
    delta = changes(root, base, head, path)
    if not delta:
        return [], [], []
    contract = contracts.get(path)
    if contract and [ast_hash(before), ast_hash(after)] == contract["source_pair"]:
        # Direct changed tests still execute; only the reviewed scaffolding dependency
        # fan-out is replaced by its declared contract/invariant tests.
        own = [
            path + "::" + k.replace(".", "::")
            for k in delta
            if k.split(".")[-1].startswith("test_") and k in units(after)
        ]
        declared = contract.get("components", contract_components)
        if not declared:
            raise ValueError("test_support_contract_coverage_missing")
        return own, list(declared), []
    is_test = Path(path).name.startswith("test_")
    if not is_test:
        return [], [], ["unreviewed_shared_test_support:" + path]
    if not before:
        return [path], [], []
    if "@module" in delta or any(not k.startswith("test_") for k in delta):
        return [path], [], ["unreviewed_test_helper_or_module_change:" + path]
    # Deleting a test cannot authorize removing its coverage silently.
    if any(k not in units(after) for k in delta):
        return [], [], ["removed_test_requires_ownership_review:" + path]
    return [path + "::" + k for k in delta], [], []


def select(root, changed, config, *, source_sha, merge_base):
    from pr_selection import digest, is_documentation, normalize, suite_for

    owners = config["ownership"]
    components = owners["components"]
    targets, reasons, used, blocked, evidence = set(), {}, set(), [], {}
    release, needs_pg = set(), False
    docs, relevant = True, False

    def add(target, reason):
        path = target.split("::", 1)[0]
        if Path(path).is_absolute() or ".." in Path(path).parts:
            raise ValueError("external_test_target")
        if not (root / path).resolve().is_relative_to(root.resolve()):
            raise ValueError("external_test_target")
        if not (root / path).exists():
            # Optional new component tests are not required until its source exists.
            raise ValueError("missing_required_test_target")
        suite_for(target)
        targets.add(target)
        reasons.setdefault(target, set()).add(reason)

    def component(name, reason):
        nonlocal needs_pg
        if name not in components:
            raise ValueError("unknown_owned_component")
        used.add(name)
        spec = components[name]
        if not spec.get("evidence") or not spec.get("tests"):
            raise ValueError("component_evidence_missing")
        for target in spec["tests"]:
            # Optional entries allow the same reviewed selector on pre-Roles trees.
            if (root / target.split("::", 1)[0]).exists():
                add(target, name + ":" + reason)
            elif not (
                target in spec.get("optional", [])
                and spec.get("optional_until_source")
                and not (root / spec["optional_until_source"]).exists()
            ):
                raise ValueError("missing_required_test_target")
        needs_pg |= spec.get("postgres", False)
        if spec.get("release"):
            release.add(name)

    for path in sorted(set(changed)):
        if Path(path).is_absolute() or ".." in Path(path).parts:
            raise ValueError("invalid_changed_path")
        explicit_resource = any(fnmatch.fnmatchcase(path, m["path"]) for m in owners["resources"])
        if is_documentation(path) and not explicit_resource:
            continue
        docs = False
        if any(path.startswith(p) for p in config["delegated_prefixes"]):
            continue
        relevant = True
        # Existing isolated applications retain whole owning scope, not inferred readers.
        isolated = next(
            (c for c in config["isolated_components"] if path.startswith(c + "/")), None
        )
        if isolated:
            add(isolated + "/tests", "isolated_complete_owner:" + isolated)
            used.add(isolated)
            continue
        if path.startswith("tools/ci/") or path.startswith(".github/workflows/"):
            component("ci", path)
            continue
        if "/tests/" in path or path.startswith("tests/"):
            if path.endswith(".py"):
                direct, declared, errors = test_changes(
                    root,
                    merge_base,
                    source_sha,
                    path,
                    owners.get("test_support", {}),
                    owners.get("support_contract", {}).get("components", ()),
                )
                for t in direct:
                    add(t, "changed_native_function_all_parameters:" + path)
                for c in declared:
                    component(c, "reviewed_test_contract:" + path)
                blocked.extend(errors)
                evidence[path] = dict(kind="test_declarations", targets=direct, contracts=declared)
            else:
                mappings = [m for m in owners["resources"] if fnmatch.fnmatchcase(path, m["path"])]
                if not mappings:
                    blocked.append("unowned_test_resource:" + path)
                for m in mappings:
                    for c in m["components"]:
                        component(c, "complete_resource_owner:" + path)
            continue
        mappings = [m for m in owners["sources"] if fnmatch.fnmatchcase(path, m["path"])]
        if path.endswith(".py") and mappings:
            for m in mappings:
                if "source_pair" in m and m["source_pair"] != [
                    ast_hash(blob(root, merge_base, path)),
                    ast_hash(blob(root, source_sha, path)),
                ]:
                    blocked.append("shared_declaration_contract_changed:" + path)
                    mappings = []
                    break
            delta = changes(root, merge_base, source_sha, path)
            evidence[path] = dict(kind="python_declarations", changed=delta)
            for declaration in delta:
                matches = [
                    m
                    for m in mappings
                    if any(fnmatch.fnmatchcase(declaration, p) for p in m["declarations"])
                ]
                if not matches:
                    blocked.append("unowned_declaration:" + path + ":" + declaration)
                for m in matches:
                    for c in m["components"]:
                        component(c, path + "::" + declaration)
        else:
            mappings = [m for m in owners["resources"] if fnmatch.fnmatchcase(path, m["path"])]
            if not mappings:
                blocked.append("unowned_executable_or_resource:" + path)
            for m in mappings:
                for c in m["components"]:
                    component(c, "complete_resource_owner:" + path)
        # Shared safety is a named contract, never every API endpoint.
    if used - {"ci", *config["isolated_components"]}:
        component("state_safety", "cross_component_invariants")
    if relevant and not targets and not blocked:
        blocked.append("empty_owned_selection")
    suites = {}
    normalized = normalize(targets)
    for target in normalized:
        suite, pytest_config = suite_for(target)
        suites.setdefault(suite, dict(config=pytest_config, targets=[]))["targets"].append(target)
    payload = dict(
        version=1,
        scope="targeted_pr",
        source_sha=source_sha,
        merge_base=merge_base,
        selector_sha=os.getenv("CI_SELECTOR_SHA") or source_sha,
        changed_files=sorted(set(changed)),
        docs_only=docs,
        relevant=relevant,
        needs_database=needs_pg,
        delegated_check=config["delegated_check"] if not relevant and not docs else None,
        buckets=sorted(used),
        full_regression_required=bool(release),
        full_reasons=sorted(release),
        release_qualification="REQUIRED_EXACT_RELEASE_SHA",
        blocked_reasons=sorted(set(blocked)),
        suites=suites,
        target_reasons={
            t: sorted(
                {
                    r
                    for k, rs in reasons.items()
                    if k == t or k.startswith(t + "::") or k.startswith(t + "/")
                    for r in rs
                }
            )
            for t in normalized
        },
        fixture_dependencies={},
        impact_evidence=evidence,
        config_sha256=digest(config),
        expected_full_api_root="apps/api/tests",
    )
    return {**payload, "content_sha256": digest(payload)}
