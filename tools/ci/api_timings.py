"""Run unchanged pytest selection with payload-free progress and timing artifacts.

Raw pytest output stays in a temporary file, never in Actions logs/artifacts.
Only this plugin's bounded records cross a separate pipe to the parent process.
No test selection, fixture, marker, timeout or database policy is changed.
"""

import argparse
import hashlib
import inspect
import json
import os
import re
import signal
import subprocess
import sys
import tempfile
import threading
import time
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from pathlib import Path

import pytest

ROOT = Path.cwd().resolve()  # Invoke from the repository root (also for read-only inventories).
GROUPS = ("fast_api", "sqlite_integration", "postgres_integration", "heavy_f05", "other_review")
FAST_MODULES = {"test_auth_settings.py", "test_f04_equivalent_proposals.py"}


def safe_id(node_id):
    """Parametrization IDs can contain complete user messages or credentials."""
    base, parameter, _ = node_id.partition("[")
    base = re.sub(r"[^a-zA-Z0-9_./:-]", "_", base)
    return base + (
        "[case-" + hashlib.sha256(node_id.encode()).hexdigest() + "]" if parameter else ""
    )


def relative(path):
    try:
        return Path(path).resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return "external_fixture"


def group_for(module, fixtures, postgres):
    """Proposed ownership, NOT permission to run a group concurrently."""
    if postgres or any(name.endswith("_postgres.py") for name in fixtures.values()):
        return "postgres_integration", "postgres marker or resolved PostgreSQL fixture"
    if Path(module).name.startswith(("test_f05_", "test_z_f05_")):
        return "heavy_f05", "F05 lifecycle family; fixture metadata retained for isolation review"
    if fixtures.get("engine") == "apps/api/tests/conftest.py":
        return "sqlite_integration", "resolved per-test tmp_path SQLite engine"
    if Path(module).name in FAST_MODULES:
        return "fast_api", "reviewed settings/typed-model module without database fixture"
    return "other_review", "not proven isolated; retain serial execution pending review"


def write_reports(output, collection, cases, exitcode, seconds, diagnostics=(), selection=None):
    output.mkdir(parents=True, exist_ok=True)
    ids = [item["case_id"] for item in collection]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate collected test IDs")
    modules = defaultdict(lambda: dict(tests=0, seconds=0.0))
    outcomes = Counter()
    for case in cases.values():
        modules[case["module"]]["tests"] += 1
        modules[case["module"]]["seconds"] += sum(case["phases"].values())
        outcomes[case["outcome"] if case["complete"] else "incomplete"] += 1
    unexecuted = sorted(set(ids) - {key for key, case in cases.items() if case["complete"]})
    summary = dict(
        exitcode=exitcode,
        wall_seconds=seconds,
        collected=len(collection),
        collection_ids=ids,
        diagnostics=list(diagnostics),
        selection=selection,
        outcomes=dict(outcomes),
        testcases=list(cases.values()),
        unexecuted_or_incomplete=unexecuted,
        groups={
            group: [x["case_id"] for x in collection if x["group"] == group] for group in GROUPS
        },
        modules=dict(sorted(modules.items())),
        slowest_30=sorted(cases.values(), key=lambda x: sum(x["phases"].values()), reverse=True)[
            :30
        ],
    )
    for name, payload in (("collection.json", collection), ("timings.json", summary)):
        (output / name).write_text(json.dumps(payload, indent=2) + "\n")
    suite = ET.Element(
        "testsuite", name="api", tests=str(len(cases) + len(diagnostics)), time=str(seconds)
    )
    for case in cases.values():
        element = ET.SubElement(
            suite,
            "testcase",
            classname=case["module"],
            name=case["node_id"],
            time=str(sum(case["phases"].values())),
        )
        if not case["complete"]:
            ET.SubElement(element, "error", message="Test did not complete")
        elif case["outcome"] != "passed":
            tag = (
                "skipped"
                if case["outcome"] == "skipped"
                else (
                    "error"
                    if any(f["phase"] != "call" for f in case.get("failures", []))
                    else "failure"
                )
            )
            ET.SubElement(element, tag, message="See safe phase/outcome in timings.json")
    for index, diagnostic in enumerate(diagnostics):
        element = ET.SubElement(suite, "testcase", classname="pytest", name=f"diagnostic_{index}")
        ET.SubElement(element, "error", message=diagnostic["kind"])
    for outcome in ("failure", "error", "skipped"):
        suite.set(
            outcome + ("s" if outcome != "skipped" else ""),
            str(len(suite.findall(f"testcase/{outcome}"))),
        )
    ET.ElementTree(suite).write(output / "junit.xml", encoding="utf-8", xml_declaration=True)
    rows = [
        "## API timing (setup + call + teardown)",
        "",
        f"Exit: {exitcode}; collected: {len(collection)}; outcomes: {dict(outcomes)}; "
        f"unexecuted/incomplete: {len(unexecuted)}; wall: {seconds:.3f}s.",
        "",
        "| Module | Reported cases | Seconds |",
        "| --- | ---: | ---: |",
    ]
    rows += [
        f"| {module} | {v['tests']} | {v['seconds']:.3f} |" for module, v in sorted(modules.items())
    ]
    rows += ["", "### Slowest 30", "", "| Safe node ID | Seconds |", "| --- | ---: |"]
    rows += [f"| {c['node_id']} | {sum(c['phases'].values()):.3f} |" for c in summary["slowest_30"]]
    (output / "summary.md").write_text("\n".join(rows) + "\n")
    return summary


class TimingPlugin:
    def __init__(self, fd, private_manifest, plan=None, partition=None, plan_sha=None):
        os.set_inheritable(fd, False)
        self.stream = os.fdopen(fd, "w", buffering=1)
        self.private_manifest = private_manifest
        self.items = {}
        self.plan = plan
        self.partition = partition
        self.plan_sha = plan_sha

    def emit(self, kind, **values):
        self.stream.write(json.dumps(dict(kind=kind, **values)) + "\n")

    def describe(self, items):
        for item in items:
            # Resolved fixture definitions, not a filename-only isolation guess.
            fixtures = {
                name: relative(inspect.getsourcefile(definitions[-1].func) or "")
                for name, definitions in item._fixtureinfo.name2fixturedefs.items()
                if definitions
            }
            module = relative(item.path)
            group, reason = group_for(
                module, fixtures, item.get_closest_marker("postgres") is not None
            )
            entry = dict(
                case_id=hashlib.sha256(item.nodeid.encode()).hexdigest(),
                node_id=safe_id(item.nodeid),
                module=module,
                fixtures=fixtures,
                group=group,
                reason=reason,
            )
            self.items[item.nodeid] = entry
        return [self.items[item.nodeid] for item in items]

    def pytest_collection_modifyitems(self, session, config, items):
        inventory = self.describe(items)
        if self.plan:
            import api_partitions

            plan = json.loads(Path(self.plan).read_text())
            if api_partitions.digest(plan) != self.plan_sha:
                raise ValueError("Plan checksum mismatch")
            revision = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
            expected = api_partitions.selection(plan, self.partition, inventory, revision)
            selected = [item for item in items if self.items[item.nodeid]["case_id"] in expected]
            config.hook.pytest_deselected(items=[item for item in items if item not in selected])
            items[:] = selected
            self.emit(
                "selection",
                partition=self.partition,
                plan_sha256=self.plan_sha,
                inventory_sha256=plan["inventory_sha256"],
                expected_count=len(expected),
            )

    def pytest_collection_finish(self, session):
        raw = []
        for item in session.items:
            entry = self.items[item.nodeid]
            self.emit("collected", **entry)
            raw.append(
                dict(node_id=item.nodeid, **{k: v for k, v in entry.items() if k != "node_id"})
            )
        if self.private_manifest:
            path = Path(self.private_manifest)
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "w", opener=lambda p, flags: os.open(p, flags, 0o600)) as handle:
                os.fchmod(handle.fileno(), 0o600)
                json.dump(raw, handle, indent=2)

    def pytest_keyboard_interrupt(self, excinfo):
        self.emit("interrupted")

    def pytest_collectreport(self, report):
        if report.failed:
            self.emit("collection_error", node_id=safe_id(report.nodeid))

    def pytest_internalerror(self, excrepr, excinfo):
        frame = excinfo.traceback[-1]
        self.emit(
            "internal_error",
            filename=relative(frame.path),
            line=frame.lineno,
            family=re.sub("[^a-zA-Z0-9_]", "_", excinfo.type.__name__)[:64],
        )

    def pytest_runtest_logstart(self, nodeid, location):
        self.emit("start", node_id=self.items[nodeid]["node_id"])

    @pytest.hookimpl(wrapper=True)
    def pytest_runtest_makereport(self, item, call):
        report = yield
        family = call.excinfo.type.__name__ if call.excinfo else None
        report.ci_exception_family = (
            family
            if family
            in {
                "AssertionError",
                "ValueError",
                "TypeError",
                "ValidationError",
                "RuntimeError",
                "PermissionError",
                "OSError",
            }
            else ("OtherException" if family else None)
        )
        return report

    def pytest_runtest_logreport(self, report):
        self.emit(
            "phase",
            **{k: self.items[report.nodeid][k] for k in ("case_id", "node_id", "module", "group")},
            phase=report.when,
            seconds=report.duration,
            outcome=report.outcome,
            exception_family=report.ci_exception_family,
        )


def run(args):
    output = Path(args.output).resolve()
    read_fd, write_fd = os.pipe()
    command = [sys.executable, str(Path(__file__).resolve()), "_pytest", str(write_fd)]
    command += [
        args.private_manifest or "",
        args.plan or "",
        args.partition or "",
        args.plan_sha256 or "",
        *args.pytest_args,
    ]
    started = time.monotonic()
    collection, cases, diagnostics, receipt = [], {}, [], None
    stopped = []
    # Even capfd.disabled(), exception reprs and plugin warnings cannot leak to CI.
    with tempfile.TemporaryFile() as private_output:
        process = subprocess.Popen(
            command,
            stdout=private_output,
            stderr=private_output,
            pass_fds=(write_fd,),
            start_new_session=True,
        )
        killers = []

        def terminate(reason="timeout", signum=signal.SIGTERM):
            if process.poll() is not None:
                return
            stopped.append(reason)
            try:
                os.killpg(process.pid, signum)
            except ProcessLookupError:
                pass

            def kill():
                if process.poll() is None:
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass

            killer = threading.Timer(5, kill)
            killer.daemon = True
            killers.append(killer)
            killer.start()

        timer = threading.Timer(args.timeout_seconds, terminate) if args.timeout_seconds else None
        handlers = {s: signal.getsignal(s) for s in (signal.SIGINT, signal.SIGTERM)}
        for signum in handlers:
            signal.signal(signum, lambda signum, frame: terminate("interrupted", signum))
        if timer:
            timer.start()
        os.close(write_fd)
        with os.fdopen(read_fd) as events:
            for line in events:
                event = json.loads(line)
                kind = event.pop("kind")
                if kind == "collected":
                    collection.append(event)
                elif kind == "selection":
                    receipt = event
                elif kind == "start":
                    print("START " + event["node_id"], flush=True)
                elif kind == "collection_error":
                    diagnostics.append(dict(kind=kind, **event))
                    print("COLLECTION_ERROR " + event["node_id"], flush=True)
                elif kind == "internal_error":
                    diagnostics.append(dict(kind=kind, **event))
                    print("PYTEST_INTERNAL_ERROR " + json.dumps(event), flush=True)
                elif kind == "interrupted":
                    diagnostics.append(dict(kind=kind))
                elif kind == "phase":
                    case = cases.setdefault(
                        event["case_id"],
                        dict(
                            case_id=event["case_id"],
                            node_id=event["node_id"],
                            module=event["module"],
                            group=event["group"],
                            phases={},
                            phase_counts={},
                            failures=[],
                            outcome="passed",
                            complete=False,
                        ),
                    )
                    case["phases"][event["phase"]] = event["seconds"]
                    counts = case["phase_counts"]
                    counts[event["phase"]] = counts.get(event["phase"], 0) + 1
                    if event["outcome"] == "failed" or case["outcome"] == "passed":
                        case["outcome"] = event["outcome"]
                    if event["outcome"] == "failed":
                        failure = dict(
                            phase=event["phase"], exception_family=event["exception_family"]
                        )
                        case["failures"].append(failure)
                        print(f"FAIL {case['node_id']} {json.dumps(failure)}", flush=True)
                    case["complete"] = event["phase"] == "teardown"
                    if case["complete"]:
                        elapsed = sum(case["phases"].values())
                        print(
                            f"END {case['node_id']} {case['outcome']} {elapsed:.3f}s",
                            flush=True,
                        )
        code = process.wait()
        if timer:
            timer.cancel()
        for killer in killers:
            killer.cancel()
        for signum, handler in handlers.items():
            signal.signal(signum, handler)
    if stopped:
        diagnostics.append(dict(kind=stopped[0]))
        code = 124 if stopped[0] == "timeout" else 130
    if code == 5 and receipt is not None and receipt["expected_count"] == 0 and not diagnostics:
        code = 0  # Verified, explicitly required empty partition; never an omitted job.
    summary = write_reports(
        output, collection, cases, code, time.monotonic() - started, diagnostics, receipt
    )
    print(
        json.dumps({k: summary[k] for k in ("exitcode", "wall_seconds", "collected", "outcomes")})
    )
    for case in summary["slowest_30"]:
        print(f"SLOW {sum(case['phases'].values()):.3f}s {case['node_id']}")
    return code


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "_pytest":
        plugin = TimingPlugin(int(sys.argv[2]), sys.argv[3], *sys.argv[4:7])
        return pytest.main(["-p", "no:terminal", *sys.argv[7:]], plugins=[plugin])
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    parser.add_argument(
        "--private-manifest", help="Local only: full node IDs; never upload this file"
    )
    parser.add_argument("--plan")
    parser.add_argument("--partition")
    parser.add_argument("--plan-sha256")
    parser.add_argument("--timeout-seconds", type=float)
    args, pytest_args = parser.parse_known_args()
    if any((args.plan, args.partition, args.plan_sha256)) and not all(
        (args.plan, args.partition, args.plan_sha256)
    ):
        parser.error("Plan, partition and plan checksum are required together")
    if args.timeout_seconds is not None and args.timeout_seconds <= 0:
        parser.error("Timeout must be positive")
    args.pytest_args = pytest_args[1:] if pytest_args[:1] == ["--"] else pytest_args
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
