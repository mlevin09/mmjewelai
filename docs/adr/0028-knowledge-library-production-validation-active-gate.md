# ADR 0028: Knowledge Library production validation and ACTIVE promotion gate

Status: Accepted. Date: 2026-10-03.

## Context

Knowledge Library Contract v1.0.0 deliberately separates COMPILED from ACTIVE. Steps 9–13 now
provide the production compiler/validator, parser/matcher, runtime state/policy engine, Prompt
Enrichment integration, and cross-package behavioral regression coverage. The remaining production
boundary is an explicit promotion gate that can prove which exact compiled runtime was validated
before it is allowed to be selected for production use.

The compiler must remain incapable of emitting ACTIVE records. A green test run alone is not an
activation record because it does not bind all required validation categories to the exact runtime
hash and artifact version.

## Decision

Add a deterministic production-validation report and a separate ACTIVE release envelope.

The required validation categories are:

- compiler and contract validation;
- provenance integrity;
- language matcher behavior;
- runtime policy behavior;
- Prompt Enrichment integration;
- behavioral regression.

Each category records PASS, EXPECTED_GAP, or FAIL plus an evidence reference. EXPECTED_GAP is
blocking for production activation, exactly as frozen in Contract v1.0.0. Missing required checks
make the report INCOMPLETE. Any EXPECTED_GAP or FAIL makes it BLOCKED. Only a complete all-PASS
report is ELIGIBLE.

ACTIVE promotion is a separate deterministic operation. It requires exact equality of package ID,
artifact version, and compiled-runtime SHA-256 between the validation report and the compiled
runtime. The resulting immutable ACTIVE envelope records the validation-report SHA-256 and the
runtime SHA-256. It does not mutate the compiled runtime and does not change source records to
ACTIVE.

The activation gate is provider-neutral and does not execute tests, network calls, or deployment
actions. CI remains responsible for producing evidence. A production catalog is not activated merely
because this gate exists.

## Alternatives

Allowing the compiler to set `active_for_production=true` would collapse compilation and release
authority and violate Contract v1.0.0. Treating EXPECTED_GAP as acceptable would contradict the
frozen contract. A mutable boolean on the compiled runtime would lose the exact validation lineage.

## Consequences

Production selection can require an explicit ACTIVE envelope rather than treating any COMPILED
runtime as deployable. Revalidation produces a new report hash and therefore a distinct release
lineage. A catalog with unresolved gaps remains non-active.

The first real Knowledge Library catalog still requires its own complete validation report before an
ACTIVE envelope may be created. This ADR does not claim that such a catalog has already been
promoted.

## Validation

Unit tests cover all-PASS eligibility, EXPECTED_GAP and FAIL blocking, incomplete reports, exact
runtime identity binding, deterministic report hashing, and immutable ACTIVE envelope creation.
Cross-package behavioral regression remains part of Runtime API CI.
