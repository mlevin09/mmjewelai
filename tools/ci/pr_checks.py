"""Execute selected native pytest groups with complete, redacted accounting."""

import argparse
import json
import math
import subprocess
import sys
import time
from pathlib import Path

from api_partitions import validate_artifacts
from full_units import covers
from pr_selection import validate_selection
from qualification import validate_qualification


def invoke(root, output, config, targets, *, collect=False, timeout=1200):
    command = [
        sys.executable,
        str(root / "tools/ci/api_timings.py"),
        "--output",
        str(output),
        "--timeout-seconds",
        str(timeout),
        "--",
        "-c",
        config,
        *targets,
        "-p",
        "no:cacheprovider",
    ]
    if collect:
        command.append("--collect-only")
    result = subprocess.run(command, cwd=root, capture_output=True, text=True, timeout=timeout + 15)
    report_path = output / "timings.json"
    if not report_path.exists():
        raise ValueError("required_result_artifact_missing")
    report = json.loads(report_path.read_text())
    if result.returncode or report["exitcode"] or report["diagnostics"]:
        # Never echo raw pytest exception text/payload from a failed child.
        raise ValueError("selected_collection_or_execution_failed")
    return report


def verify_execution(report, expected):
    cases = report["testcases"]
    ids = [c["case_id"] for c in cases]
    if (
        report["exitcode"] != 0
        or report["diagnostics"]
        or len(ids) != len(set(ids))
        or set(ids) != set(expected)
        or report["collection_ids"] != expected
        or any(
            not c["complete"]
            or c["outcome"] != "passed"
            or c["phase_counts"] != dict(setup=1, call=1, teardown=1)
            or set(c["phases"]) != {"setup", "call", "teardown"}
            or any(
                type(v) not in (int, float) or not math.isfinite(v) or v < 0
                for v in c["phases"].values()
            )
            for c in cases
        )
    ):
        raise ValueError("selected_test_coverage_or_outcome_failed")


def execute(root, manifest, output, *, qualification=None, metadata=None):
    validate_selection(manifest, root)
    output.mkdir(parents=True, exist_ok=True)
    result = dict(
        scope="targeted_pr",
        source_sha=manifest["source_sha"],
        result="failure",
        full_regression_required=manifest["full_regression_required"],
        groups={},
        qualified_by_full=False,
    )
    started = time.monotonic()
    try:
        if manifest["docs_only"] or not manifest["relevant"]:
            subprocess.run(
                ["git", "diff", "--check", manifest["merge_base"], manifest["source_sha"]],
                cwd=root,
                check=True,
                capture_output=True,
            )
            result["result"] = "success"
            return result
        if qualification is not None:
            validate_qualification(qualification, metadata, manifest["source_sha"])
            if not covers(qualification["unit_suites"], manifest["suites"]):
                raise ValueError("full_qualification_does_not_cover_selection")
        full_inventory = None
        if "api" in manifest["suites"]:
            full_inventory = invoke(
                root,
                output / "api-native-inventory",
                "apps/api/pyproject.toml",
                ["apps/api/tests"],
                collect=True,
                timeout=120,
            )["collection_ids"]
        collections = {}
        for suite, group in manifest["suites"].items():
            report = invoke(
                root,
                output / (suite.replace("/", "_") + "-collection"),
                group["config"],
                group["targets"],
                collect=True,
                timeout=120,
            )
            ids = report["collection_ids"]
            if not ids or len(ids) != len(set(ids)):
                raise ValueError("empty_or_duplicate_selected_collection")
            if suite == "api" and not set(ids).issubset(full_inventory):
                raise ValueError("selected_api_identity_not_native")
            collections[suite] = ids
            result["groups"][suite] = dict(
                selected=len(ids), case_ids=ids, targets=group["targets"]
            )
        saturated = full_inventory is not None and set(collections.get("api", [])) == set(
            full_inventory
        )
        if saturated:
            result["full_regression_required"] = True
        if qualification is not None:
            if full_inventory is not None and set(qualification["api_cases"]) != set(
                full_inventory
            ):
                raise ValueError("full_qualification_inventory_mismatch")
            # Full run on this SHA already includes the selected product/package
            # suites. Do not repeat them to reopen a high-risk gate.
            for suite, ids in collections.items():
                if suite != "api" and not set(ids).issubset(
                    qualification["unit_suites"].get(suite, {}).get("case_ids", [])
                ):
                    raise ValueError("full_qualification_missing_selected_unit_cases")
            result["qualified_by_full"] = True
        else:
            if saturated:
                raise ValueError("entire_api_scope_requires_manual_full_regression")
            for suite, group in manifest["suites"].items():
                report = invoke(
                    root,
                    output / (suite.replace("/", "_") + "-execution"),
                    group["config"],
                    group["targets"],
                )
                verify_execution(report, collections[suite])
                validate_artifacts(output / (suite.replace("/", "_") + "-execution"), report)
                result["groups"][suite]["seconds"] = report["wall_seconds"]
        if manifest["blocked_reasons"]:
            raise ValueError("unmapped_impact_requires_routing_review")
        if result["full_regression_required"] and qualification is None:
            raise ValueError("manual_full_qualification_required_before_merge")
        result["result"] = "success"
        return result
    finally:
        result["seconds"] = round(time.monotonic() - started, 3)
        (output / "pr-result.json").write_text(json.dumps(result, indent=2) + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--qualification")
    parser.add_argument("--metadata")
    args = parser.parse_args()
    manifest = json.loads(Path(args.manifest).read_text())
    kwargs = {}
    if args.qualification or args.metadata:
        if not (args.qualification and args.metadata):
            raise ValueError("missing_full_qualification_pair")
        kwargs = dict(
            qualification=json.loads(Path(args.qualification).read_text()),
            metadata=json.loads(Path(args.metadata).read_text()),
        )
    execute(Path.cwd(), manifest, Path(args.output), **kwargs)
    print("targeted_pr_gate: PASS (not full regression unless explicitly qualified)")


if __name__ == "__main__":
    try:
        main()
    except (ValueError, KeyError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        print("targeted_pr_gate: FAIL; inspect bounded selection/result artifacts")
        raise SystemExit(1) from None
