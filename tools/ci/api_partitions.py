"""Deterministic required API partitions and fail-closed coverage gate (CI only)."""

import argparse
import ast
import hashlib
import json
import math
import re
import subprocess
from pathlib import Path

PARTITIONS = [f"isolated-{i}" for i in range(4)] + ["serial"]
ELIGIBLE = {"fast_api", "sqlite_integration", "heavy_f05"}


def digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def file_digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def source_identity(root):
    paths = sorted((root / "apps/api/tests").rglob("*.py"))
    return digest({p.relative_to(root).as_posix(): file_digest(p) for p in paths})


def test_sources(root, module, fixtures):
    """Pin test module, resolved fixtures, and transitive local test helpers."""
    tests = root / "apps/api/tests"
    pending = [root / module, *(root / p for p in fixtures.values() if p != "external_fixture")]
    pending.append(tests / "conftest.py")
    found = {}
    while pending:
        path = pending.pop().resolve()
        if not path.is_relative_to(tests.resolve()) or path.as_posix() in found:
            continue
        if not path.is_file():
            raise ValueError("Missing test dependency")
        found[path.as_posix()] = file_digest(path)
        for node in ast.walk(ast.parse(path.read_text())):
            names = (
                [node.module]
                if isinstance(node, ast.ImportFrom)
                else ([a.name for a in node.names] if isinstance(node, ast.Import) else [])
            )
            for name in names:
                dependency = tests / ((name or "").split(".")[0] + ".py")
                if dependency.is_file():
                    pending.append(dependency)
    return {Path(p).relative_to(root).as_posix(): sha for p, sha in sorted(found.items())}


def validate_plan(plan):
    if plan.get("version") != 1 or set(plan["partitions"]) != set(PARTITIONS):
        raise ValueError("Invalid partition plan")
    assigned = [case for ids in plan["partitions"].values() for case in ids]
    if len(assigned) != len(set(assigned)) or set(assigned) != set(plan["cases"]):
        raise ValueError("Partition overlap or missing collection")
    if any(not re.fullmatch("[0-9a-f]{64}", value) for value in assigned):
        raise ValueError("Invalid case identity")
    if any(
        plan["cases"][case]["partition"] != partition
        for partition, ids in plan["partitions"].items()
        for case in ids
    ):
        raise ValueError("Inconsistent partition assignment")
    return plan


TIMING_PATH = "tools/ci/timing_weights.json"


def timing_costs(weights):
    """Historical scheduling estimates, never authority to omit/isolate tests."""
    if weights.get("version") != 1 or weights.get("content_sha256") != digest(
        {k: v for k, v in weights.items() if k != "content_sha256"}
    ):
        raise ValueError("Invalid historical timing manifest")
    records = weights["cases"]
    if not records:
        raise ValueError("Empty historical timing manifest")
    for identity, record in records.items():
        if (
            not re.fullmatch("[0-9a-f]{64}", identity)
            or type(record["milliseconds"]) is not int
            or record["milliseconds"] <= 0
        ):
            raise ValueError("Invalid historical timing cost")
        if record["basis"] == "measured":
            phases = record["phases"]
            if (
                set(phases) != {"setup", "call", "teardown"}
                or any(
                    type(v) not in (int, float) or not math.isfinite(v) or v < 0
                    for v in phases.values()
                )
                or record["milliseconds"] != max(1, math.ceil(sum(phases.values()) * 1000))
            ):
                raise ValueError("Invalid historical measured phases")
        elif record["basis"] == "function_profile_max":
            peers = {
                k: r
                for k, r in records.items()
                if r["basis"] == "measured"
                and (r["module"], r["function"], r.get("profile"))
                == (record["module"], record["function"], record.get("profile"))
            }
            if not peers:
                raise ValueError("No measured timing peer")
            maximum = max(r["milliseconds"] for r in peers.values())
            witness = min(k for k, r in peers.items() if r["milliseconds"] == maximum)
            if record["milliseconds"] != maximum or record["witness_case_id"] != witness:
                raise ValueError("Invalid timing estimate witness")
        else:
            raise ValueError("Unknown timing basis")
    return records


def balance(plan, weights):
    records = timing_costs(weights)
    loads = dict.fromkeys(PARTITIONS[:-1], 0)
    costs = {}
    for identity, case in plan["cases"].items():
        if case["partition"] == "serial":
            continue  # Timings cannot override source/fixture isolation.
        function = case["node_id"].split("::")[-1].split("[")[0]
        record = records.get(identity)
        if record and (record["module"], record["function"]) == (case["module"], function):
            cost = record["milliseconds"]
        else:
            # New reviewed cases remain mandatory. Their cost is explicitly an
            # estimate, not zero, and never an excuse to drop the case.
            peers = [r["milliseconds"] for r in records.values() if r["module"] == case["module"]]
            cost = max(peers or [r["milliseconds"] for r in records.values()])
        costs[identity] = cost
    for partition in loads:
        plan["partitions"][partition] = []
    for identity in sorted(costs, key=lambda k: (-costs[k], k)):
        partition = min(loads, key=lambda p: (loads[p], p))
        loads[partition] += costs[identity]
        plan["cases"][identity]["partition"] = partition
        plan["partitions"][partition].append(identity)
    plan["partitions"] = {p: sorted(ids) for p, ids in plan["partitions"].items()}
    plan["timing"] = dict(weights_sha256=digest(weights), projected_phase_milliseconds=loads)


def make_plan(collection, review, root, revision, *, weights=None):
    cases, groups, cache = {}, {p: [] for p in PARTITIONS}, {}
    for item in collection:
        identity = item["case_id"]
        if identity in cases:
            raise ValueError("Duplicate collected case")
        sources = cache.setdefault(item["module"], {})
        # Fixture graphs can differ by case, so the cache key includes fixture definitions.
        key = digest(item["fixtures"])
        if key not in sources:
            sources[key] = test_sources(root, item["module"], item["fixtures"])
        pins = sources[key]
        reviewed = bool(pins) and all(sha in review.get(path, []) for path, sha in pins.items())
        isolated = item["group"] in ELIGIBLE and reviewed
        partition = f"isolated-{int(identity, 16) % 4}" if isolated else "serial"
        cases[identity] = dict(
            module=item["module"],
            node_id=item["node_id"],
            group=item["group"],
            partition=partition,
            isolation="reviewed_test_sources" if isolated else "serial_required",
        )
        groups[partition].append(identity)
    plan = dict(
        version=1,
        source_revision=revision,
        source_sha256=source_identity(root),
        inventory_sha256=digest(collection),
        partitions={p: sorted(ids) for p, ids in groups.items()},
        cases=cases,
    )
    if weights is not None:
        balance(plan, weights)
    return validate_plan(plan)


def selection(plan, partition, collection, revision, root=None):
    validate_plan(plan)
    if partition not in plan["partitions"] or revision != plan["source_revision"]:
        raise ValueError("Partition or source revision mismatch")
    if digest(collection) != plan["inventory_sha256"]:
        raise ValueError("Actual full collection differs from planned inventory")
    if source_identity(root or Path.cwd()) != plan["source_sha256"]:
        raise ValueError("Test sources changed after planning")
    if "timing" in plan:
        path = (root or Path.cwd()) / TIMING_PATH
        if (
            not path.is_file()
            or digest(json.loads(path.read_text())) != plan["timing"]["weights_sha256"]
        ):
            raise ValueError("Timing manifest changed after planning")
    return set(plan["partitions"][partition])


def gate(plan, reports, upstream):
    validate_plan(plan)
    errors, seen, results = [], set(), {}
    if set(reports) - set(PARTITIONS):
        errors.append("unexpected_partition")
    if len(upstream) != 3 or any(value != "success" for value in upstream):
        errors.append("upstream_not_success")
    expected_sha = digest(plan)
    for partition in PARTITIONS:
        report = reports.get(partition)
        if report is None:
            errors.append("missing_partition:" + partition)
            continue
        receipt = report.get("selection") or {}
        expected = set(plan["partitions"][partition])
        if (
            receipt.get("partition") != partition
            or receipt.get("plan_sha256") != expected_sha
            or receipt.get("inventory_sha256") != plan["inventory_sha256"]
            or receipt.get("expected_count") != len(expected)
        ):
            errors.append("partition_binding:" + partition)
        collected = report.get("collection_ids", [])
        cases = report.get("testcases", [])
        ids = [case["case_id"] for case in cases]
        if (
            len(collected) != len(set(collected))
            or set(collected) != expected
            or report.get("collected") != len(expected)
        ):
            errors.append("selected_collection:" + partition)
        if len(ids) != len(set(ids)) or set(ids) != expected or seen.intersection(ids):
            errors.append("execution_coverage:" + partition)
        seen.update(ids)
        if report.get("exitcode") != 0 or report.get("diagnostics"):
            errors.append("execution_failure:" + partition)
        for case in cases:
            if (
                not case.get("complete")
                or case.get("outcome") != "passed"
                or set(case.get("phases", {})) != {"setup", "call", "teardown"}
                or case.get("phase_counts") != dict(setup=1, call=1, teardown=1)
                or any(
                    type(v) not in (int, float) or not math.isfinite(v) or v < 0
                    for v in case.get("phases", {}).values()
                )
            ):
                errors.append("nonpassing_or_incomplete:" + partition)
                break
        results[partition] = dict(
            expected=len(expected), reported=len(ids), wall_seconds=report.get("wall_seconds")
        )
    if seen != set(plan["cases"]):
        errors.append("global_coverage")
    return dict(
        result="failure" if errors else "success",
        errors=sorted(set(errors)),
        expected=len(plan["cases"]),
        reported=len(seen),
        partitions=results,
    )


def validate_artifacts(folder, report):
    import xml.etree.ElementTree as ET

    for name in ("timings.json", "collection.json", "junit.xml", "summary.md"):
        if not (folder / name).is_file() or not (folder / name).stat().st_size:
            raise ValueError("Missing required result artifact: " + name)
    collected = json.loads((folder / "collection.json").read_text())
    ids = [item["case_id"] for item in collected]
    if len(ids) != len(set(ids)) or ids != report["collection_ids"]:
        raise ValueError("Collection artifact mismatch")
    suite = ET.parse(folder / "junit.xml").getroot()
    actual = [(c.get("classname"), c.get("name")) for c in suite.findall("testcase")]
    expected = [(c["module"], c["node_id"]) for c in report["testcases"]]
    # Diagnostics can only fail the gate. Their generic JUnit errors are not
    # substituted for successful executions or counted as design test cases.
    expected += [("pytest", f"diagnostic_{i}") for i in range(len(report["diagnostics"]))]
    if actual != expected or len(actual) != len(set(actual)):
        raise ValueError("JUnit case artifact mismatch")
    if int(suite.get("tests", "-1")) != len(actual):
        raise ValueError("JUnit count mismatch")
    failed_xml = bool(
        suite.findall("testcase/failure")
        or suite.findall("testcase/error")
        or suite.findall("testcase/skipped")
    )
    nonpassing = bool(
        report["diagnostics"]
        or any(not c["complete"] or c["outcome"] != "passed" for c in report["testcases"])
    )
    if failed_xml != nonpassing:
        raise ValueError("JUnit outcome artifact mismatch")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    plan_parser = sub.add_parser("plan")
    plan_parser.add_argument("--collection", required=True)
    plan_parser.add_argument("--review", default="tools/ci/isolation.json")
    plan_parser.add_argument("--output", required=True)
    gate_parser = sub.add_parser("gate")
    gate_parser.add_argument("--plan", required=True)
    gate_parser.add_argument("--plan-sha256", required=True)
    gate_parser.add_argument("--reports", required=True)
    gate_parser.add_argument("--output", required=True)
    gate_parser.add_argument("--upstream", action="append", required=True)
    args = parser.parse_args()
    if args.command == "plan":
        revision = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
        plan = make_plan(
            json.loads(Path(args.collection).read_text()),
            json.loads(Path(args.review).read_text()),
            Path.cwd(),
            revision,
            weights=json.loads(Path(TIMING_PATH).read_text()),
        )
        Path(args.output).write_text(json.dumps(plan, indent=2) + "\n")
        print("plan_sha256=" + digest(plan))
        print(json.dumps({p: len(ids) for p, ids in plan["partitions"].items()}))
        return 0
    plan = json.loads(Path(args.plan).read_text())
    if digest(plan) != args.plan_sha256:
        raise ValueError("Aggregate plan checksum mismatch")
    reports = {}
    for path in Path(args.reports).rglob("timings.json"):
        report = json.loads(path.read_text())
        partition = report.get("selection", {}).get("partition")
        if partition in reports:
            raise ValueError("Duplicate partition report")
        validate_artifacts(path.parent, report)
        reports[partition] = report
    if set(reports) - set(PARTITIONS):
        raise ValueError("Unexpected partition report")
    result = gate(plan, reports, args.upstream)
    Path(args.output).write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result))
    return int(result["result"] != "success")


if __name__ == "__main__":
    raise SystemExit(main())
