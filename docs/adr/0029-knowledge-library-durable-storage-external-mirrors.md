# ADR 0029: Knowledge Library durable artifact storage and external mirrors

Status: Accepted. Date: 2026-10-03.

## Context

Knowledge Library Contract v1.0.0 and ADR 0028 define deterministic compilation and an explicit
ACTIVE promotion gate, but they do not define how versioned source, compiled runtime, manifest, and
integrity metadata are retained after validation. Step 15 also validates that the architecture extends
beyond the original solitaire slice and requires approved artifacts to be mirrorable to project
document storage without making that external system part of runtime correctness.

The storage boundary must preserve the frozen contract, provider neutrality, deterministic runtime
hashing, and fail-closed activation semantics.

## Decision

A durable Knowledge Library release is an immutable directory addressed by
`package_id/artifact_version`. Publishing writes four canonical UTF-8 JSON artifacts:

- `source.json` — the validated Knowledge Library bundle;
- `runtime.json` — deterministic compiler output;
- `manifest.json` — compiler manifest bound to the runtime SHA-256;
- `checksums.json` — SHA-256 values for the three canonical artifacts.

Publishing the same package/version is idempotent only when all canonical bytes are identical.
Different content at an existing package/version is rejected. Loading is fail-closed: missing files,
checksum mismatch, deterministic recompilation mismatch, manifest mismatch, or path/identity
mismatch rejects the release.

The storage implementation is filesystem-rooted and provider-neutral. Its configured root may be a
durable mounted volume or another directory supplied by deployment infrastructure. No cloud storage
provider is embedded in the domain package.

Google Drive, when used for JewelAI project retention, is an external governed mirror of approved
durable artifacts and governance records. It is not a runtime source of truth, activation authority,
or fallback for missing runtime artifacts. Synchronization must preserve package/version identity and
the checksum metadata; a Drive copy never changes ACTIVE eligibility.

The second validation slice is `jewelai.validation.three_stone`. It reuses Contract v1.0.0 and the
existing center/side-stone schema and stable `group_id` binding. It does not introduce a new
Knowledge Library contract or infer absent side-stone groups.

## Alternatives

Storing only compiled runtime JSON would lose source and manifest lineage. Overwriting an existing
package/version would make validation evidence non-reproducible. Making Google Drive the runtime
store would couple domain correctness to a collaboration provider and would weaken provider-neutral
runtime behavior. Redesigning the frozen contract for the three-stone slice is unnecessary because
the existing contract and schema express the required behavior.

## Consequences

Knowledge releases can be retained and reloaded with deterministic integrity verification. External
mirrors can be replaced without changing the domain contract. Any mirror outage affects document
synchronization only, not runtime validation or activation.

A deployment must configure a genuinely durable root; an ephemeral filesystem does not become
durable merely by using this API. External mirror synchronization remains an explicit delivery
operation and must not be reported as complete unless the target system confirms it.

## Validation

Domain tests cover idempotent publication, immutable package/version behavior, tamper detection,
path safety, and deterministic reload verification. The three-stone vertical slice exercises
compiler, RU/EN matcher behavior, stable side-stone group binding, Prompt Enrichment blocking for an
unknown group, and the all-PASS ACTIVE promotion gate. Runtime API CI executes this slice alongside
the existing behavioral regression suite.
