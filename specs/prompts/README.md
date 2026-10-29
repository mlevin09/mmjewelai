# Prompt Compiler v1.0.0

Prompt Compiler v1 is deterministic, provider-neutral derived-output infrastructure. Its canonical
input is a validated immutable `DesignRevision`; prompt text is never authoritative state or a
business-rule engine. The compiler schema version and implementation version are `1.0.0`. The
initial `jewelry_visualization` template, template version `1.0.0`, is published in prompt artifact
`1.0.0` with `proposed_pending_product_review` status. This validates integrity and lineage, not
aesthetic image-generation quality.

The declarative artifact contains fixed English provider-facing instructions and labels only. It
cannot execute code, traverse fields, select questions, decide readiness, or add jewelry defaults.
Compiler code uses fixed schema traversal order and canonical DomainId values. Conversational role
and locale are not compiler inputs.

Known values and `NotApplicable` states are represented as structured entries. Unknown and absent
fields are omitted. Derived uncertainty, knowledge source identity/version, assumed rationale and
rule identity/version, and not-applicable reasons are structured disclosures and visible in the
rendered disclosure section. Raw messages and customer content are never consumed.

Every locked KnownValue or locked `NotApplicable` entry produces exactly one structured lock
constraint and one canonical rendering under `LOCKED CONSTRAINTS — MUST NOT CHANGE`. Validation
recompiles from the exact revision and template and requires model equality; this fails closed for
missing/extra/changed locks, altered text or hash, disclosure changes, or lineage mismatches.

The content hash is lowercase SHA-256 of the exact UTF-8 prompt text. No unit conversion, numerical
rounding, gemstone inference, asset fetching, provider syntax, model parameter, network call, or
generation behavior exists in v1.

Generate and verify the [JSON Schema](schema.json):

```sh
python -m jewelai_prompts.schema specs/prompts/schema.json
python -m pytest -c packages/prompts/pyproject.toml packages/prompts/tests -q
python -m ruff check packages/prompts
python -m ruff format --check packages/prompts
```

## Prompt Enrichment final output v1.1.0

Step #12 adds a separate [provider-neutral output schema](internal-final-prompt-schema.json) for the
approved Prompt Enrichment Module boundary. `UserReadableJewelryDescription` is deterministic EN/RU
review prose; it is not authoritative state. `InternalFinalPrompt` is the structured handoff built
from the same exact Product State revision, immutable enrichment cycle, verified ACTIVE Knowledge
release pin, artifact versions, existing Rules decision, and applicable decision lineage.

The v1.1 output adds hashed, typed evidence for explicit requirements, prohibitions and preservation
instructions that Product State v1 cannot represent without semantic or provenance loss. Active
evidence is emitted as a constraint; superseded and rejected history remains auditable but is not
emitted as active authority; unresolved evidence remains unresolved. Evidence is bound to the
session, organization, source message/span, Product State revision and enrichment cycle. Unaccepted
recommendations remain evidence rather than requirements. Input inconsistencies fail closed.
Neither contract changes `CompiledPrompt`, selects a provider, calls a network service, activates a
catalog, or changes generation behavior.

Step #14C adds the independently versioned
[Internal Final Prompt handoff schema](internal-final-prompt-handoff-schema.json) `1.0.0`. The
handoff embeds one already-verified `InternalFinalPrompt` rather than translating or duplicating its
semantic payload, and binds it to exact organization/session, Product State revision, enrichment
cycle, Knowledge release hashes, readiness, and a canonical handoff SHA-256. Its internal runtime
builder reconstructs this state from durable organization-scoped history. It is not a provider
request, production-generation authorization, or replacement for legacy `CompiledPrompt`.

## Current canonical IFP/handoff 2.1.0

Current writers emit structured enrichment **1.3.0**, without calling the legacy compiler, followed
by canonical IFP/handoff **2.1.0**. IFP text alone permits **32,000 Unicode characters / 128,000 UTF-8
bytes**. Description 1.0 and downstream execution rendering retain **20,000 / 80,000**. All bounds
fail closed; facts/locks/provenance are never truncated to fit. CompiledPrompt 1.0 and canonical
IFP/handoff 2.0 readers retain their original limits and hashes.

Use `decode_canonical_internal_final_prompt` / `decode_canonical_handoff` for exact 2.0/2.1 dispatch;
unsupported/mixed versions fail. The additive current schema is
[canonical-preparation-schema.json](canonical-preparation-schema.json); the older schema files
above remain frozen. No historical record is rewritten. See
[ADR 0034](../../docs/adr/0034-versioned-ifp-capacity-v2-1.md) for operation boundaries and PCAP tests.
