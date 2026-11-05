"""Exact-SHA manual full-regression evidence. No dispatch, status writes or deployment."""

import argparse
import json
import os
import re
import urllib.error
import urllib.request
from pathlib import Path

from api_partitions import PARTITIONS, digest
from full_units import check_proof

REPOSITORY = "mlevin09/mmjewelai"
WORKFLOW = ".github/workflows/full-regression.yml"


def validate_metadata(metadata, sha):
    if (
        metadata.get("head_sha") != sha
        or metadata.get("event") != "workflow_dispatch"
        or metadata.get("status") != "completed"
        or metadata.get("conclusion") != "success"
        or metadata.get("path", "").split("@")[0] != WORKFLOW
        or metadata.get("repository", {}).get("full_name") != REPOSITORY
    ):
        raise ValueError("full_qualification_not_available_for_exact_sha")
    return metadata


def validate_qualification(receipt, metadata, sha):
    validate_metadata(metadata, sha)
    body = {k: v for k, v in receipt.items() if k != "content_sha256"}
    cases = receipt.get("api_cases", [])
    if (
        receipt.get("content_sha256") != digest(body)
        or receipt.get("scope") != "full_regression"
        or receipt.get("source_sha") != sha
        or receipt.get("result") != "success"
        or not receipt.get("authorization_reference")
        or not receipt.get("reason")
        or receipt.get("run_id") != metadata.get("id")
        or receipt.get("attempt") != metadata.get("run_attempt")
        or not cases
        or len(cases) != len(set(cases))
        or any(not re.fullmatch(r"[0-9a-f]{64}", c) for c in cases)
        or set(receipt.get("partitions", [])) != set(PARTITIONS)
    ):
        raise ValueError("invalid_full_qualification")
    check_proof(receipt.get("unit_suites", {}))
    return receipt


def emit(plan, gate, *, sha, run_id, attempt, authorization, reason, unit_suites):
    if (
        plan["source_revision"] != sha
        or gate.get("result") != "success"
        or gate.get("errors")
        or gate.get("expected") != len(plan["cases"])
        or gate.get("reported") != len(plan["cases"])
        or not plan["cases"]
        or not authorization.strip()
        or not reason.strip()
    ):
        raise ValueError("incomplete_full_regression_cannot_qualify_release")
    check_proof(unit_suites)
    body = dict(
        unit_suites=unit_suites,
        scope="full_regression",
        source_sha=sha,
        result="success",
        run_id=run_id,
        attempt=attempt,
        authorization_reference=authorization,
        reason=reason,
        api_cases=sorted(plan["cases"]),
        partitions=PARTITIONS,
        plan_sha256=digest(plan),
    )
    return {**body, "content_sha256": digest(body)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    meta = sub.add_parser("metadata")
    meta.add_argument("--run-id", required=True)
    meta.add_argument("--sha", required=True)
    meta.add_argument("--output", required=True)
    stamp = sub.add_parser("emit")
    stamp.add_argument("--plan", required=True)
    stamp.add_argument("--gate", required=True)
    stamp.add_argument("--output", required=True)
    stamp.add_argument("--unit-proof", required=True)
    check = sub.add_parser("check")
    check.add_argument("--receipt", required=True)
    check.add_argument("--metadata", required=True)
    check.add_argument("--sha", required=True)
    args = parser.parse_args()
    if args.command == "metadata":
        if not args.run_id.isdigit() or not re.fullmatch("[0-9a-f]{40}", args.sha):
            raise ValueError("invalid_run_identity")
        request = urllib.request.Request(
            f"https://api.github.com/repos/{REPOSITORY}/actions/runs/{args.run_id}",
            headers={
                "Authorization": "Bearer " + os.environ["GITHUB_TOKEN"],
                "Accept": "application/vnd.github+json",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                data = json.load(response)
        except urllib.error.HTTPError as exc:
            raise ValueError("qualification_metadata_http_" + str(exc.code)) from None
        except OSError:
            raise ValueError("qualification_metadata_unavailable") from None
        validate_metadata(data, args.sha)
        # Store only bounded identity/status, not the provider response or headers.
        payload = {
            k: data[k]
            for k in ["id", "head_sha", "event", "status", "conclusion", "path", "run_attempt"]
        }
        payload["repository"] = {"full_name": REPOSITORY}
        out = Path(args.output)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(payload))
        with open(os.environ["GITHUB_OUTPUT"], "a") as handle:
            handle.write("artifact_name=full-qualification-" + str(data["run_attempt"]) + "\n")
    elif args.command == "emit":
        body = emit(
            json.loads(Path(args.plan).read_text()),
            json.loads(Path(args.gate).read_text()),
            sha=os.environ["CONFIRM_SHA"],
            run_id=int(os.environ["GITHUB_RUN_ID"]),
            attempt=int(os.environ["GITHUB_RUN_ATTEMPT"]),
            authorization=os.environ["AUTHORIZATION_REFERENCE"],
            reason=os.environ["REASON"],
            unit_suites=json.loads(Path(args.unit_proof).read_text()),
        )
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(body, indent=2))
    else:
        validate_qualification(
            json.loads(Path(args.receipt).read_text()),
            json.loads(Path(args.metadata).read_text()),
            args.sha,
        )
        print("exact_sha_full_qualification: PASS")


if __name__ == "__main__":
    try:
        main()
    except (ValueError, KeyError) as exc:
        # All application error messages here are bounded codes; no raw HTTP body.
        print(type(exc).__name__ + ": qualification_check_failed")
        raise SystemExit(1) from None
