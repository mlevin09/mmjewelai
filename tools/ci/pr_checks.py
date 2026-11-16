"""Execute selected native pytest groups with complete, redacted accounting."""

import argparse
import json
import math
import re
import subprocess
import sys
import time
from pathlib import Path

from api_partitions import timing_costs, validate_artifacts
from full_units import covers
from pr_selection import validate_selection
from qualification import validate_qualification


class SelectedTestsFailed(ValueError):
    """Observed test failures, distinct from missing/invalid execution evidence."""


# Guardrail, not a test exemption: oversized scopes are BLOCKED for routing review.
# Full qualification remains a separate explicitly authorized workflow.
MAX_AUTOMATIC_PR_CASES = 800


def enforce_automatic_case_budget(collections, qualification, *, limit=MAX_AUTOMATIC_PR_CASES):
    """Refuse runaway PR test execution before invoking any selected test body."""
    if qualification is None and sum(len(case_ids) for case_ids in collections.values()) > limit:
        raise ValueError("automatic_pr_risk_budget_exceeded")


def entire_api_scope(root, targets):
    """Cheap path-only guard; do not import/collect the entire API for a narrow selection."""
    files = list((root / "apps/api/tests").rglob("test_*.py"))
    return bool(files) and all(
        any(
            "::" not in target
            and (
                file.relative_to(root).as_posix() == target
                or file.relative_to(root).as_posix().startswith(target.rstrip("/") + "/")
            )
            for target in targets
        )
        for file in files
    )


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
    if not collect and any(c.get("outcome") == "failed" for c in report.get("testcases", [])):
        raise SelectedTestsFailed("selected_tests_failed")
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
    output.mkdir(parents=True, exist_ok=True)
    result = dict(
        scope="targeted_pr",
        source_sha=manifest["source_sha"],
        result="failure",
        status="BLOCKED",
        reason="execution_incomplete",
        full_regression_required=manifest["full_regression_required"],
        merge_base=manifest["merge_base"],
        selector_sha=manifest.get("selector_sha") or manifest["source_sha"],
        components=manifest["buckets"],
        release_qualification="NOT_QUALIFIED",
        groups={},
        qualified_by_full=False,
    )
    started = time.monotonic()
    try:
        validate_selection(manifest, root)
        if manifest["blocked_reasons"]:
            raise ValueError("unmapped_impact_requires_routing_review")
        if manifest["docs_only"] or not manifest["relevant"]:
            subprocess.run(
                ["git", "diff", "--check", manifest["merge_base"], manifest["source_sha"]],
                cwd=root,
                check=True,
                capture_output=True,
            )
            result["result"] = "success"
            result.update(status="NOT_APPLICABLE", reason="no_backend_tests_required")
            return result
        if qualification is not None:
            validate_qualification(qualification, metadata, manifest["source_sha"])
            if not covers(qualification["unit_suites"], manifest["suites"]):
                raise ValueError("full_qualification_does_not_cover_selection")
        saturated = "api" in manifest["suites"] and entire_api_scope(
            root, manifest["suites"]["api"]["targets"]
        )
        if saturated:
            result["full_regression_required"] = True
            if qualification is None:
                raise ValueError("unbounded_api_scope_requires_routing_review")
        collections = {}
        for suite, group in manifest["suites"].items():
            if suite == "api" and saturated:
                # Validated exact-SHA full receipt already proves this entire collection.
                ids = qualification["api_cases"]
                collections[suite] = ids
                result["groups"][suite] = dict(
                    selected=len(ids), case_ids=ids, targets=group["targets"]
                )
                continue
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
            collections[suite] = ids
            result["groups"][suite] = dict(
                selected=len(ids), case_ids=ids, targets=group["targets"]
            )
            weights_path = root / "tools/ci/timing_weights.json"
            if weights_path.exists():
                weights = json.loads(weights_path.read_text())
                costs = timing_costs(weights)
                known = [costs[i]["milliseconds"] for i in ids if i in costs]
                result["groups"][suite]["historical_timing"] = dict(
                    measured_source=weights["origin"]["measurement_sha"],
                    known_case_seconds=round(sum(known) / 1000, 3),
                    unknown_cases=len(ids) - len(known),
                    limitation="Historical partial estimate; not current wall time/isolation proof",
                )
        enforce_automatic_case_budget(collections, qualification)
        if qualification is not None:
            if not set(collections.get("api", [])).issubset(qualification["api_cases"]):
                raise ValueError("full_qualification_missing_selected_api_cases")
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
                raise ValueError("unbounded_api_scope_requires_routing_review")
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
        # Complete PR evidence is sufficient for a PR PASS. Only an independently
        # validated full receipt can qualify the exact release SHA; never infer
        # release readiness from targeted test success.
        if qualification is not None:
            result["release_qualification"] = "QUALIFIED_EXACT_SHA"
        result["result"] = "success"
        result.update(status="PASS", reason="selected_tests_passed")
        return result
    except (ValueError, KeyError, OSError, subprocess.SubprocessError) as error:
        reason = str(error)
        if not re.fullmatch(r"[a-z_]{1,80}", reason):
            reason = "execution_environment_or_evidence_invalid"
        result.update(
            status="FAIL" if isinstance(error, SelectedTestsFailed) else "BLOCKED", reason=reason
        )
        raise
    finally:
        result["seconds"] = round(time.monotonic() - started, 3)
        failures = []
        for path in sorted(output.glob("*-execution/timings.json")):
            report = json.loads(path.read_text())
            for case in report.get("testcases", []):
                if case.get("outcome") != "passed" or not case.get("complete"):
                    failures.append(
                        {k: case.get(k) for k in ("case_id", "node_id", "outcome", "failures")}
                    )
        result["failed_case_count"] = len(failures)
        result["failed_cases"] = failures[:20]
        result["failure_artifact"] = "*-execution/timings.json"
        (output / "pr-result.json").write_text(json.dumps(result, indent=2) + "\n")
        rows = [
            "## Risk-based PR gate",
            "",
            f"Status: **{result['status']}**; reason: `{result['reason']}`.",
            f"Source: `{result['source_sha']}`; merge base: `{result['merge_base']}`; "
            f"selector: `{result['selector_sha']}`.",
            f"Components: {', '.join(result['components']) or 'none'}.",
            f"Elapsed: {result['seconds']}s. Release: **{result['release_qualification']}**.",
            "Full Regression remains a separate exact-release-SHA obligation; "
            "no automatic dispatch.",
            "",
            "| Suite | Collected cases | Execution seconds |",
            "|---|---:|---:|",
        ]
        for suite, group in result["groups"].items():
            rows.append(
                f"| {suite} | {group['selected']} | {group.get('seconds', 'NOT EXECUTED')} |"
            )
        rows += ["", "### Selected targets and reasons"]
        for target, reasons in manifest.get("target_reasons", {}).items():
            extra = (
                f"; +{len(reasons) - 4} origins in pr-selection.json" if len(reasons) > 4 else ""
            )
            rows.append(f"- `{target}`: " + "; ".join(reasons[:4]) + extra)
        if manifest.get("blocked_reasons"):
            rows += ["", "### Unresolved ownership", *manifest["blocked_reasons"]]
        if failures:
            rows += ["", "### Failed cases (bounded; full safe details in timing artifacts)"]
            rows += [f"- `{x['node_id']}`: {x['outcome']}" for x in failures[:20]]
        (output / "summary.md").write_text("\n".join(rows) + "\n")
        summary = {k: result[k] for k in ("status", "source_sha", "reason", "seconds")}
        summary["scopes"] = sorted(manifest["suites"])
        summary["selected_cases"] = sum(g.get("selected", 0) for g in result["groups"].values())
        print(json.dumps(summary))


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


if __name__ == "__main__":
    try:
        main()
    except (ValueError, KeyError, OSError, subprocess.SubprocessError):
        print("targeted_pr_gate: non-success; inspect bounded selection/result artifacts")
        raise SystemExit(1) from None
