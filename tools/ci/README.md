# Risk-based PR checks (EN MASTER)

CI-RISK-002 / ADR0045. Active `pr_routes.json` version2 extends the existing selector,
native pytest reporter and fail-closed runner. `Runtime API` / job `runtime` remains
the required PR identity. No branch protection, product semantics or database guard
is changed. See [release decision](../../docs/adr/0045-risk-based-pr-and-release-qualification.md).

## Selection

- Compare the exact PR head against its actual merge base, across all feature commits.
- Explicit component ownership maps changed Python declarations to direct and integration
  contracts. A Roles change does not select every Parser, Prompts, provider or API package.
- Changed native test functions select all their parametrized cases. No parameter sampling.
- Current shared bootstrap/helper transitions are registered with complete before/after
  semantic source hashes and explicit contract tests. Future changes invalidate the pair
  and BLOCK until their dependency coverage is reviewed. An import is not coverage proof.
- Unknown executable declarations, helper/fixture changes and resources BLOCK with a path
  and declaration reason. There is no v2-to-v1 fallback. Complete resource ownership takes
  precedence over documentation extension. The v1 synthetic fixture-policy regressions remain.
- Web/infra delegate to existing independent checks. Isolated STT owns its full native tests,
  never Torch/CUDA/model weights. CI-only executes only CI tooling, without API or migration.
- Named state/authority, tenant, CAS/rollback and migration invariants accompany actual
  backend risk. PostgreSQL is serial behind the unchanged repository/job/URL/container/
  cluster/freshness gate. Never run destructive tests on a merely test-looking URL.

## Execution and truthful outcomes

All selected native collections are inspected BEFORE executing test bodies. More than800
cases BLOCK as `automatic_pr_risk_budget_exceeded`; the cap is not raised and does not make
oversized coverage green. Unknown ownership blocks before dependency install/DDL.
Whole-API requests are blocked before collection pending a bounded risk review.

Execution must exactly match native collection, including all parameter cases and complete
passed setup/call/teardown. Missing, duplicate, skipped, interrupted or incomplete cases and
missing artifacts block; actual test failures FAIL. No continue-on-error or retry loop.
Superseded automatic PR checks cancel; manually authorized Full Regression is not cancelled.

`summary.md` / Actions summary contains source/merge-base/selector SHAs, component families,
targets/reasons, actual collected counts and measured duration, bounded failed-case references,
and release status. Full reasons remain in the selection artifact. Historical timing estimates
are explicitly partial: known case seconds plus unmeasured case count, not current wall time
or permission for parallelism. Raw exception bodies, prompts, credentials and private payloads
never enter these reports. Parameter IDs are hashed by the existing reporter.

## PR evidence is not release qualification

A successful complete targeted run returns PASS, with `release_qualification=NOT_QUALIFIED`
unless a validated exact-SHA Full receipt was supplied. Critical risk reasons remain recorded.
Full Regression remains manual, separately authorized, exact-SHA and complete. Its four
isolated API jobs plus serial PostgreSQL stage and coverage aggregate are unchanged.
No Full dispatch occurs from PR CI. Required check identities/permissions remain unchanged.

**Release enforcement Owner gate:** existing deployment workflows do not consume that receipt.
`release-gate.proposed.patch` is unapplied and `qualification.py latest` is read-only discovery.
After explicit approval, the proposed preprod insertion validates the successful exact-SHA
Full run and attempt-bound complete receipt BEFORE GCP auth/image build. It does not mutate
GitHub policies or auto-run Full. Until approved/wired, the separation is NOT approved for
integration/activation; a green PR is not a qualified release. See ADR0045 for the exact gate.
Production workflow is unchanged.

## Bounded real-world measurement

`reference-qualification.json` pins actual ROLES-001 source/base. The dedicated reference
workflow runs only when that descriptor or its workflow changes. It reuses the native runner
and independent disposable PostgreSQL service; no new test platform, provider calls or
product edits. Subject SHA and candidate selector SHA are both reported. Only CI tooling and
CI workflow overlays are allowed; product tree changes are checked absent. This is evidence
about the candidate selector on real Role code, not a required-status override for PR178,
not Full Regression and not release qualification. Ordinary CI-only Runtime remains separate.

## Focused validation

```sh
python3 -m pytest -c apps/api/pyproject.toml tools/ci/tests -q
python3 -m ruff check tools/ci
python3 -m ruff format --check tools/ci
bash -n tools/ci/install_runtime.sh
git diff --check
```

Do not invoke full Runtime API or `full_units.py` as a selector smoke. No manual Full Regression
without explicit authorization. Source-pair registrations and ownership evidence require
independent review; test success alone is not acceptance of coverage sufficiency.
