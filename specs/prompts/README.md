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
