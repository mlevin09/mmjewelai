# Risk-based PR CI (CI-RISK-BASED-001)

Local review candidate; not activated, pushed or measured on GitHub. No product,
product-test assertion, migration, provider or deployment changes. PR143/144 are
not imported or modified. Only the reviewed CI utilities from local `d0000a8` are
reused. This is pytest selection/reporting, not a new test framework.

## Automatic PR gate

`Runtime API` / job `runtime` keeps its existing required-check identity. Every PR
against `jewelai-v2` receives a gate, including docs-only PRs; no workflow path
filter or conditional required job can leave a missing/skipped check. There is
no push trigger, duplicate dispatch, schedule or automatic full regression.

`pr_selection.py` computes **git merge-base(PR target SHA, PR head SHA)** and
selects:

1. Entire new/modified pytest files, including all new parametrized cases.
2. Explicit component/dependent regression scopes from `pr_routes.json`.
3. Reverse transitive imports of changed local test helpers.
4. The four existing module-smoke targets in that same configuration.
5. Mandatory authority, evidence, persistence and authorization scopes by risk.

Selection is normalized so a whole directory/file subsumes child targets. Each
suite retains its native pytest configuration. Native collection then proves
that selected API cases belong to the full API inventory. Collection alone never
runs fixtures/tests. Empty/duplicate/uncollectable selections, missing artifacts,
failed/skipped/incomplete tests or duplicate/missing phases fail. A whole-API
selection requires manual Full Regression rather than silently launching the
entire API suite. No selected test is removed to meet a time goal.

Unknown executable/data impact fails explicitly, even when the smoke passes.
Text extensions are not documentation exemptions. Explicit docs/governance/README
conventions remain lightweight; fixtures, runtime data and resources do not.
**Reader recognition is not proof of complete dependency coverage.** No fixture
AST-reader inference is used. Resources require a reviewed `fixture_scopes`
entry with `resources` (exact path/directory prefix), `tests` (complete owning
pytest directory) and `evidence` explaining why it covers all consumers. Whole
directories are collected/executed, never only recognized reader files.

There are deliberately **no live fixture mappings** yet: shared API resources
have no established safe narrower ownership boundary. Such changes fail with
`unmapped_fixture_data` before running tests. Do not map shared resources to a
convenient subset merely to clear CI. A future mapping requires demonstrated
complete ownership and review; a nonempty justification alone is not evidence.
Mappings cannot use globs, external/missing directories, file-only targets or the
whole `apps/api/tests` suite. An unowned resource blocks, never automatically
launches 2000+ API tests. Runtime data also needs complete ownership, even if an
ordinary component regression route happens to match it. Existing Web delegation
is unchanged; its independent full Web gate remains responsible for Web scope.

Synthetic controls declare one self-contained nested test namespace and prove
that its complete scope executes direct and indirect consumers, including the
previously omitted Path-variable reader. No professional/runtime fixture mapping
is activated by those tests. This is an internal CI configuration, not a product
or durable domain contract.

The smoke combines one real HTTP integration journey (J7: RU input, canonical
state, a metal-only correction, final description/IFP, persisted restart) with
three existing final-prompt unit controls for deterministic provider-neutral
output, LOCK/confirmed/prohibition and historical integrity. It uses test-only
Knowledge and fake providers; there are no paid/provider requests.

Critical contracts/migrations/shared API dispatch/fixtures preserve targeted
checks **and** keep the merge gate red until authorized exact-SHA Full Regression
qualifies that SHA. Critical checks can exceed the ordinary 5–15 minute target;
that is reported, not hidden. Required checks cannot be overridden by a different
SHA's evidence. Selection/routing/report source hashes are retained in artifacts.

## PostgreSQL remains guarded and serial

The one PostgreSQL16 service remains in job **runtime**, with the unchanged exact
repository/job/database URL/container/cluster/freshness guard, before any Alembic
or test DDL. `disposable_postgres.py` is unchanged. API execution groups are
sequential; no xdist or concurrency against shared metadata. Full Regression
runs all PostgreSQL and unresolved-isolation cases serially in a fresh runtime
job after the four isolated hosted jobs, within the existing two-hour guard.
The actual guard cannot be qualified by an untrusted local test connection.

## Full Regression is manual only

`full-regression.yml` accepts only `workflow_dispatch`, exact SHA equal to the
selected branch HEAD, reason, Owner-authorization reference and configured budget
**465 runner-minutes maximum** (15 + 4×90 + 90). No schedule, push, PR,
workflow_call or automatic workflow chaining. Inputs record approval; they do not
replace repository access control or Owner review. Do not dispatch without
explicit Owner authorization for the exact SHA/scope/budget.

The reused parallel planner retains complete native API collection. Every case
must execute once across five partitions; all upstream jobs, all four artifacts
per partition and complete passed setup/call/teardown are required. Missing,
failed/cancelled/skipped/timeout results fail. Unknown/changed isolation sources
stay serial. Timing cannot grant isolation. Historical weights are advisory,
source-pinned isolation review remains separate. Full unit suites use their
existing native configs with the same outcome accounting; scope inventory drift
(new package/root tests) fails until explicitly included. All root Knowledge
catalog tests are included; no production catalog is activated.

Only a successful complete Full run emits a qualification receipt. It binds the
source SHA, complete API cases, complete unit case IDs/targets, all partitions,
plan hash, run/attempt and authorization. A manually authorized lightweight gate
recheck downloads that artifact and verifies read-only GitHub run metadata
(repository, workflow, dispatch event, exact SHA, success and attempt), plus
current native collection/selection equality. It does not rerun unchanged tests,
dispatch Full, write statuses or override unknown impact. Actions permission is
read-only. Full receipt retention is30days, normal bounded artifacts3days.

Full Regression is mandatory for release qualification on the exact release
commit. This code emits/checks evidence; it is **not a new release workflow or an
enforced release policy for unmodified external deployment workflows**. An Owner
must require that receipt in release qualification. No deployment code changed.

## Required-check rollout / publication stop

Original candidate `f82aa1a713c9d2689957fb52fc5de934590eeb8e` was reconciled
with merged F06 target `03bda61ba43f10a2a5aaaaeeb5abe432c3a5c9c8`; its product tree
is preserved. First-publication trigger inspection finds no automatic workflow
matching a feature-branch push. A Draft PR's merge-ref workflow uses this targeted
Runtime API definition, not a second sequential base workflow. Domain/Web/Infra
filters do not match this CI-only diff; Full stays manual. This is source-based
routing evidence, **not a hosted execution or publication authorization**.
No push/PR is performed until the existing Owner publication gate is satisfied.

The observed check name is `runtime`; the `Runtime API` label/job spelling is retained.
Full also has a `runtime` job, so exact required context/app/workflow and duplicate-
name behavior require admin verification. Domain/Web/Infrastructure workflows
are unchanged. Branch-protection API inspection returned403, so exact live admin
required-check configuration is NOT VERIFIED. Before activation the Owner must
confirm required identity/context and independently review this semantic gate
change. Initial hosted targeted CI and required-check behavior are NOT TESTED.

GitHub requires a dispatchable workflow file on the default branch for manual
execution. Default branch is `main`, this candidate targets `jewelai-v2` only;
`main` has no new Full workflow. Thus manual registration/availability is a
**rollout prerequisite, not demonstrated here**. This task does not authorize
changing main/default branch. Do not introduce a push-trigger workaround. The
Owner must explicitly choose/authorize the smallest registration arrangement
before claiming Full Regression is operationally available.

Revert the CI-only commit through review to restore the old sequential gate if
needed. There is no application/database/deployment rollback.

## Cheap validation and timing limits

Run CI helper tests, YAML/shell syntax, selected native collection and exactly the
small smoke. Never invoke `full_units.py` or the full API test bodies as a cheap
check. Redacted reporter arguments must not include `-q` (terminal plugin is off).

```sh
python -m pytest -c apps/api/pyproject.toml tools/ci/tests -q
python -m ruff check tools/ci
python -m ruff format --check tools/ci
bash -n tools/ci/install_runtime.sh
```

The reporter discards raw pytest output; only hashed identities, bounded family/
status and timing enter artifacts. Never upload optional private raw-node maps,
DBs, credentials or user payloads. Selected timing reports disclose local test
execution only. Dependency setup and hosted total duration, 5–15m target, hosted
critical checks/PG and full execution remain NOT MEASURED until authorized runs.
Historical2071 baseline/2072 F06 inventory receipts and reviewed timing evidence
are reused for unchanged API sources; they are not claimed as new product PASS.
