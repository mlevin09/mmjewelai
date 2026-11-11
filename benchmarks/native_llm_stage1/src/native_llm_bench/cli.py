"""Offline validation/preview/import; opt-in direct local execution and private export."""

import argparse
import json
from pathlib import Path

from . import storage
from .contracts import SEED, Config, InvalidArtifact, execution_plan, load, validate_runtime
from .corpus import import_sources, validate_evaluator, validate_stage1
from .runner import _validate_result, execute


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="command", required=True)
    validate = sub.add_parser("validate")
    validate.add_argument("--runtime", type=Path, required=True)
    validate.add_argument("--evaluator", type=Path)
    importer = sub.add_parser(
        "import-corpus", help="offline exact NB snapshots -> separate artifacts"
    )
    importer.add_argument("--sources", type=Path, required=True)
    importer.add_argument("--provenance", type=Path, required=True)
    importer.add_argument("--output", type=Path, required=True)
    for name in ("plan", "run", "resume"):
        cmd = sub.add_parser(name)
        cmd.add_argument("--runtime", type=Path, required=True)
        cmd.add_argument("--config", type=Path, required=True)
        cmd.add_argument("--model-manifest", type=Path, required=True)
        cmd.add_argument("--seed", type=int)
        cmd.add_argument("--sessions", help="comma-separated session IDs")
        cmd.add_argument("--exclude-holdouts", action=argparse.BooleanOptionalAction, default=None)
        if name == "run":
            cmd.add_argument("--output", type=Path, required=True)
            cmd.add_argument("--rerun-of", type=Path)
        if name == "resume":
            cmd.add_argument("directory", type=Path)
            cmd.add_argument("--retry-uncertain", action="store_true")
    inspect = sub.add_parser("inspect")
    inspect.add_argument("directory", type=Path)
    export = sub.add_parser("export", help="explicit private full-transcript export, no grading")
    export.add_argument("directory", type=Path)
    export.add_argument("--output", type=Path, required=True)
    export.add_argument("--runtime", type=Path)
    export.add_argument("--evaluator", type=Path)
    return p


def run(args):
    if args.command == "import-corpus":
        runtime, evaluator = import_sources(args.sources, load(args.provenance))
        args.output.mkdir(mode=0o700, parents=True, exist_ok=False)
        storage.write(args.output / "runtime.json", runtime)
        storage.write(args.output / "evaluator.json", evaluator)
        storage.write(
            args.output / "manifest.json",
            {
                "runtime_file_sha256": __import__("hashlib")
                .sha256((args.output / "runtime.json").read_bytes())
                .hexdigest(),
                "evaluator_file_sha256": __import__("hashlib")
                .sha256((args.output / "evaluator.json").read_bytes())
                .hexdigest(),
                "source_hashes": runtime["sources"],
            },
        )
        return {"status": "VALID", **validate_stage1(runtime)}, 0
    if args.command == "validate":
        corpus = validate_runtime(load(args.runtime))
        summary = (
            validate_stage1(corpus)
            if corpus["corpus_id"] == "jewelai.native.stage1"
            else {
                "sessions": len(corpus["sessions"]),
                "user_turns": sum(len(s["turns"]) for s in corpus["sessions"]),
            }
        )
        if args.evaluator:
            validate_evaluator(load(args.evaluator), corpus)
        return {"status": "VALID", **summary}, 0
    if args.command in ("inspect", "export"):
        run_record, results = storage.read_results(args.directory)
        for result in results:
            req, _ = storage.files(
                args.directory, result["session_id"], result["turn_id"], result["attempt"]
            )
            _validate_result(load(req), result)
        if args.command == "inspect":
            return {
                "run_id": run_record["run_id"],
                "plan_sha256": run_record["plan_sha256"],
                "session_order": run_record["plan"]["session_order"],
                "attempts": len(results),
                "completed_turns": sum(r["status"] == "COMPLETED" for r in results),
                "statuses": [r["status"] for r in results],
                "in_flight_attempts": len(list((args.directory / "requests").glob("*/*/*.json")))
                - len(results),
            }, 0
        data = storage.export(args.directory)
        if args.evaluator:
            if not args.runtime:
                raise InvalidArtifact("evaluation export requires its runtime artifact")
            runtime = validate_runtime(load(args.runtime))
            from .contracts import digest

            if digest(runtime) != run_record["plan"]["runtime_artifact_sha256"]:
                raise InvalidArtifact("export runtime mismatch")
            data["evaluator"] = validate_evaluator(load(args.evaluator), runtime)
        storage.write(args.output, data)
        return {"status": "EXPORTED", "output": str(args.output), "attempts": len(results)}, 0
    corpus = validate_runtime(load(args.runtime))
    if corpus["corpus_id"] == "jewelai.native.stage1":
        validate_stage1(corpus)
    config, manifest = Config(**load(args.config)), load(args.model_manifest)
    selected = args.sessions.split(",") if args.sessions else None
    seed, exclude = args.seed, args.exclude_holdouts
    if args.command == "resume":
        old = storage.read_run(args.directory)["plan"]
        if seed is None:
            seed = old["scheduling_seed"]
        if selected is None:
            selected = old["session_order"]
        if exclude is None:
            exclude = old["exclude_holdouts"]
    seed = SEED if seed is None else seed
    exclude = bool(exclude)
    if args.command == "plan":
        return execution_plan(corpus, config, manifest, seed, selected, exclude), 0
    summary = execute(
        corpus,
        config,
        manifest,
        getattr(args, "output", None),
        seed=seed,
        selected=selected,
        exclude_holdouts=exclude,
        resume=args.directory if args.command == "resume" else None,
        retry_uncertain=getattr(args, "retry_uncertain", False),
        rerun_of=getattr(args, "rerun_of", None),
    )
    return summary, 0 if summary["status"] == "COMPLETED" else 2


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        result, status = run(args)
    except KeyboardInterrupt:
        print(json.dumps({"status": "INTERRUPTED", "outcome_may_be_unknown": True}))
        return 130
    except (InvalidArtifact, OSError, TypeError, KeyError, ValueError) as exc:
        detail = str(exc) if isinstance(exc, InvalidArtifact) else type(exc).__name__
        print(json.dumps({"status": "INVALID_FIXTURE_OR_RUN", "detail": detail}))
        return 64
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return status
