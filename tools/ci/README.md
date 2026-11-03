# Runtime API measurement and safe partitioning — local Phases 1–2

The Phase 1 instrumentation is retained. Phase 2 partitions the original node
IDs while requiring their complete union. No regression test, fixture, database
policy, required check identity or product code is changed. No additional library is introduced: Python's standard library and the
existing pytest 8.4 dependency are sufficient. The subprocess pipe targets the
existing Ubuntu runner (also tested locally on macOS).

## Safe progress and reports

Run from the repository root in the normal installed test environment:

```sh
python tools/ci/api_timings.py --output /tmp/api-timings -- \
  -c apps/api/pyproject.toml apps/api/tests
```

That is the full existing API selection; it is NOT a Phase 1 local validation
command. No full API execution is authorized for this phase.

The workflow runs backend Ruff/format before migrations or tests. All original
package suites and API tests remain required. The API command prints START/END,
phase/outcome and bounded exception families. Parametrized IDs can contain full
user messages: their bracketed portion is replaced with a SHA-256 identifier.
Use the local collection manifest to resolve a parameter when diagnosing a failure.
No exception messages, assertion values, captured logs or user properties are
published. Raw child output is discarded with its temporary file. A separate
non-inherited pipe carries only timing metadata. Pytest exit status is preserved;
fixture, collection and internal failures do not become successful runs.

Timing reports have **three-day retention** (Phase 2 additionally uploads its
plan and aggregate coverage receipt):

- `collection.json`: safe node IDs, hashes, resolved fixture source files and
  proposed groups. This is metadata, not proof of process/database isolation.
- `timings.json`: per-test setup/call/teardown seconds, outcomes, safe failure
  families, incomplete/unexecuted IDs, module totals and the 30 slowest cases.
- `junit.xml`: testcase durations and generic failure/error/skip elements; no
  stdout, stderr, properties or private failure messages.
- `summary.md`: aggregate module times and slowest 30 for the Actions summary.

Durations are elapsed pytest phases, not CPU profiles. Module totals include
setup and teardown; they do not separately attribute SQL, parsing or replay.
Abrupt runner termination can prevent final artifact creation; START still shows
the last case. Missing reports fail visibly, rather than fabricating success.
Assertions must be reproduced locally to inspect private values safely.

## Collection and proposed ownership

Collection performs no fixture setup or test calls:

```sh
python tools/ci/api_timings.py --output /tmp/api-collection \
  --private-manifest /tmp/api-private-nodes.json -- \
  -c apps/api/pyproject.toml apps/api/tests --collect-only -p no:cacheprovider
```

The optional full-ID manifest is local-only (mode 0600). Never upload it. The
workflow does not request it. Compare its IDs with native pytest collection, not
with a manually estimated test count. Group lists must be a disjoint union of
all collected IDs. Duplicate IDs fail report generation. Parametrized cases are
retained separately. No group is used to select or exclude execution in Phase 1.

| Proposed group | Evidence / limitation |
| --- | --- |
| `fast_api` | Reviewed settings and typed-equivalence modules; no DB fixture. This name is not a measured speed guarantee. |
| `sqlite_integration` | Resolved `engine` fixture is the per-test tmp-path SQLite fixture. Includes direct repository tests as well as HTTP. |
| `postgres_integration` | PostgreSQL marker or an actually resolved PostgreSQL fixture, including imported fixtures. Marker alone is not proof of safe DDL. |
| `heavy_f05` | F05 family after PostgreSQL classification; source has multi-turn/restart/capacity journeys. Timing still required. |
| `other_review` | Explicit conservative remainder; includes dynamically requested fixtures and tests with direct setup. Keep serial until reviewed. Never silently omit it. |

Local collection at integration base `bc34a789a18692caeea8342788a14485b06d15c8`:
1431 IDs = 50 fast + 806 SQLite + 424 PostgreSQL + 0 F05 + 151 other.
Native collection matched the exact IDs and order, with no duplicates or omissions.

Read-only inventory of PR #142 at `197d8a82fde45253c284103b2efc0723e63adeaf`:
2039 IDs = 50 fast + 806 SQLite + 462 PostgreSQL + 570 F05 + 151 other.
It was not executed or copied into this branch. Therefore a future run of the
1431-case integration base is not a like-for-like comparison with the previous
9502-second, 2039-case PR run. Re-inventory the eventual reviewed product HEAD.
The four known style cases remain collected and their source file is unchanged.

## Phase 1 isolation findings (retained; Phase 2 implementation follows)

1. **Job-level isolation:** SQLite `engine` uses per-test tmp-path files;
   synthetic release stores also use tmp paths. These are candidates for separate
   processes, not a blanket guarantee for all fixture/global-state interactions.
   `other_review` stays serial until dynamic fixture/direct-setup dependencies are
   reviewed. Do not enable global xdist.
2. **PostgreSQL:** the schema-isolated fixture in
   `apps/api/tests/test_generation_preparations_postgres.py` uses a random schema
   and imports the independent disposable-target gate. Older marked tests in
   `test_persistence.py` and `test_enrichment_persistence.py` also drop/recreate the
   shared default metadata. These cannot safely run concurrently on one database.
   No PostgreSQL test or migration was executed locally in this phase.
3. **Two-hour gate:** `apps/api/tests/disposable_postgres.py` binds the project,
   job ID `runtime`, exact URL/port, PostgreSQL 16 container, cluster identity and
   container age under two hours. Each gate invocation must satisfy the age, not
   just the job's first step. A queue delay before a fresh job starts is not
   container age. Running PostgreSQL after a long unrelated suite can violate
   this gate. Keep its checks unchanged. A proposed new job ID must not simply
   bypass this check; retain `runtime` or separately review an equally strict
   explicit CI identity binding. Give each PG job its own fresh service and keep
   shared-DB cases serial. If the measured group cannot finish while the gate is
   valid, split it across independently verified fresh services, never extend age.
4. **Fixture cost (hypothesis):** repeated application/release construction and
   per-case schema migration are visible in source. Setup/call/teardown timings
   are the next evidence, not grounds to widen fixture scope now.
5. **History cost (hypothesis):** preview/admitted reads reconstruct verified
   source/history; previous local observations counted repeated lexical helper
   passes, not exclusive time. Do not remove integrity validation or cache its
   conclusions to speed up CI. Runtime profiling/optimization needs separate scope.

Smallest next execution change, after timing evidence: retain one serial PG
ownership group on its verified service and divide proven SQLite HTTP groups
between separate runners using measured node times. Keep fast/other cases covered
and compare the selected manifest union against native collection before running.
Balance parametrized heavy groups by node ID, not just filename. Include every
remaining ID explicitly; fail the gate for omitted, duplicate or failed shards.

Expected file scope: `.github/workflows/runtime-api.yml`, this tooling/tests and,
only if required, reviewed test-only grouping metadata. No product changes.
Changing job/check names or required-gate aggregation requires Owner review of
the actual branch protection (the audit connection received 403). No such change
is made here. The migration commands, service and disposable gate are unchanged.

For minimum full-run cost, obtain timings during the next already-required,
Owner-authorized complete CI execution on a stable product HEAD; do not dispatch
an extra full run in Phase 1. Validate proposed partitioning with collection and
small isolation controls, then one optimized complete run on equivalent product
code/selection. Do not repeatedly run an unchanged full command. Compare wall
time, all node IDs, outcomes and skips; disclose product-code differences.

Timeout budgets must follow the measured case/group distribution. A shorter
timeout is not an optimization and must not turn unfinished coverage into PASS.
Independent jobs and grouping are proposed, not enabled. **Full CI runtime
improvement remains NOT MEASURED.**

## Phase 2: implemented locally, not pushed or executed in Actions

The Phase 1 historical inventory above is retained. The workflow now proposes
four isolated jobs and one serial ownership group; the existing `runtime` job
remains the required aggregate and keeps its PostgreSQL safety identity.

```text
prepare (lint + unchanged package suites + native full API collection + plan)
  -> api_isolated[isolated-0 .. isolated-3] (four separate hosted runners)
  -> runtime (fresh PG service -> existing safety gate -> Alembic -> serial cases)
       -> strict aggregate over all five partition artifacts
```

`api_partitions.py` assigns every collected hash once. Hash modulo four applies
only to the previously reviewed fast/SQLite/F05 candidates. This is deterministic
count distribution, NOT measured load balancing. `heavy_f05` is a family label,
not a measured cost classification. The checked-in `isolation.json` holds only
reviewed test-source SHA-256 values from the integration base and unchanged
PR #142. It includes resolved fixture sources, conftest and transitive local
helper imports. A changed/new/unreviewed source dependency defaults to the
mandatory serial group. PostgreSQL and `other_review` always remain serial.
Fixture identity and full inventory are rechecked in every execution process;
the plan binds exact source revision, test source tree, inventory and checksum.
Original pytest IDs are selected in memory; raw parameter IDs never enter shell
arguments or uploaded artifacts. No global xdist is introduced.

Isolation evidence: each concurrent job has its own process, workspace and local
filesystem. The reviewed default engine uses function-scoped `tmp_path` SQLite;
release stores and synthetic assets use local fixtures. Logging/global monkeypatch
state cannot cross runners. Isolated jobs have no PostgreSQL service/URL, WIF or
provider secrets. The conditional postgres fixture parameters retain their marker
and enter serial. Unknown dynamic/direct setup stays serial. Local representative
controls verify distinct SQLite files in separate processes; this is bounded
isolation evidence, not execution of every scenario or proof of every future test.
Any unexpected skip/incomplete case causes the aggregate to fail.

Base plan: isolated counts **246 / 195 / 221 / 194**, serial **575** (total 1431).
PR #142 plan: **393 / 359 / 338 / 336**, serial **613** (total 2039).
All four known style/KEEP failures remain assigned, their assertions unchanged.
Full F05 coverage remains required, including the future final F05 merge gate.

### Gate, failure and timeout behavior

All five artifacts are mandatory, even for an explicitly empty partition. The
same full collection must match the plan before selection. Aggregate checks exact
union, no duplicate executions, every setup/call/teardown exactly once, successful
outcomes, no skips, diagnostics or incomplete records, and three upstream results.
Missing/mismatched artifacts, failed/cancelled/skipped jobs, source/checksum drift,
collection errors and timeouts cannot produce PASS. JUnit also records collection,
internal and interruption diagnostics as errors instead of an empty green suite.

The matrix uses fail-fast=false so a known product failure does not hide siblings.
After a completed failed matrix, serial still runs for complete measurement;
`runtime` remains red because the final gate requires upstream success. A failed
prepare or cancelled/skipped matrix prevents unsafe/meaningless serial execution
and cannot turn the final gate green. There is no continue-on-error or blind retry.

| Job | Job timeout | API process limit |
| --- | ---: | ---: |
| prepare | 15 minutes | collection 120 seconds |
| each isolated runner | 60 minutes | 50 minutes |
| runtime / serial | 90 minutes | 80 minutes |

Process timeout sends TERM, then KILL after five seconds if needed, and records
124/incomplete evidence. Interruptions remain failures; a hard runner termination
may leave no artifact, which also fails the gate. Limits are safety ceilings, not
speedup claims. PostgreSQL is created only after isolated jobs complete. Its
90-minute job bound is below the unchanged two-hour gate, which is called before
any migration/DDL and again by existing fixtures. Shared default-schema
`drop_all/create_all` tests and schema-isolated tests do not run concurrently.
No PostgreSQL test/migration was run locally: no independently verified local
CI service is available. This is explicitly NOT TESTED, never a mocked PG PASS.

Workflow/job name `Runtime API` / `runtime` is preserved. Branch protection still
returns 403 to the integration: actual required rules need Owner confirmation
before publication/execution. Additional matrix status names do not replace the
aggregate. Deployment workflows and branch-protection configuration are unchanged.

### One future authorized measurement (not requested or started now)

After independent review, authorize exactly one run on an explicit product tree.
To address the 9502-second F05 baseline, use the reviewed PR #142 product tree
`197d8a82fde45253c284103b2efc0723e63adeaf` plus only this CI patch on a SEPARATE
measurement branch, only if separately authorized by Owner. Do not change PR #142.
Opening one authorized Draft CI PR triggers the normal workflow once; no dispatch
or reruns. The four known defects should keep it red while all mandatory cases
are attempted. If Owner instead chooses integration base, it measures 1431 cases
and must not be advertised as a like-for-like 2039-case speedup. Any new target
requires collection/source identity verification before interpreting comparison.

Record Actions job start/completion timestamps, queue wait, workflow duration,
all partition JSON/JUnit and aggregate receipt. Compare selected union and actual
outcomes/skips first, then wall time; distinguish native job setup from API process
time. Three-day artifact retention applies. Inspect one targeted cause after any
unexpected failure or limit; no automatic retry or remediation.

Let S be the old serial fraction of 9502 seconds (NOT MEASURED). With balanced
isolated jobs and four available runners, ideal execution is S + (9502-S)/4 plus
setup. At 10% serial this is ~51.5 minutes; at 25% ~69.3 minutes; at 50% ~99 minutes.
These are calculations, not predictions or measurements. Actual skew, PG setup,
queue capacity and additional imports may reduce benefit. Execution ceilings sum
to 165 minutes excluding queue wait; they do not promise this duration or a speedup.
Four-runner capacity is NOT VERIFIED until the authorized run. Total compute
minutes may grow from repeated setup even if wall time improves.

### Cheapest attribution of runtime candidates (proposal only)

First use measured per-case setup/call/teardown: setup is not automatically DB
migration, and call is not automatically parsing. For exact attribution, use
stdlib cProfile around the ENTIRE existing pytest protocol for ONE already-required
multi-turn HTTP case and ONE already-required PG case, in their ordinary partition
execution, only after separate approval of that CI-only hook. No extra test call,
production edit, cached integrity verdict or removed validation is needed. Export
only an allowlist of function labels with call count, self and cumulative seconds:
replay_admitted, NativePrefixReader methods, _lexical_candidates, scope validation,
Alembic upgrade/check, and Description/IFP render functions. Do not upload raw
profiles, arguments, exception payloads or test user properties. Inclusive times
nest and must not be added as exclusive costs. Record profiling overhead explicitly;
the profiled run is diagnostic and not a clean speed benchmark. This profiling
hook is NOT implemented or enabled in Phase 2. Runtime optimization remains a
separate authorization after evidence identifies the actual cost.
