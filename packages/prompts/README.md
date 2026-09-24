# JewelAI Prompt Compiler

This package compiles one validated immutable `DesignRevision` and one explicit versioned prompt
template artifact into a deterministic provider-neutral `CompiledPrompt`. It depends only on
Pydantic and `packages/domain`; it has no API, persistence, parser, provider SDK, Model Gateway,
network, image generation, clock, UUID, or randomness dependency.

Compilation traverses canonical fields in fixed schema order, sorts side-stone groups by stable
`group_id`, omits absent/Unknown states, preserves exact typed values and `NotApplicable`, and never
invents defaults. Derived uncertainty, assumed rationale, and applicability reasons remain visible
as structured disclosures and prompt text. Every lock is derived from the same canonical entries
into a structured manifest and rendered under the template's locked-constraint label.

`validate_compiled_prompt` recompiles from the pinned revision/template and requires complete model
equality, detecting altered text, hashes, entries, disclosures, metadata, or lock manifests.

```sh
python -m pip install -e './packages/domain[test]'
python -m pip install -e './packages/prompts[test]'
python -m jewelai_prompts.schema specs/prompts/schema.json
python -m pytest -c packages/prompts/pyproject.toml packages/prompts/tests -q
```
