# JewelAI parser package

This provider-neutral package validates untrusted `ParserCandidate` values and builds deterministic,
schema-safe `ParserProposal` results. It depends only on Pydantic and `packages/domain`; it has no
FastAPI, persistence, provider SDK, prompt, network, clock, UUID generation, or Rules Engine call.

`parse_full_message()` is the additive internal RU/EN intake boundary for complete user messages.
It returns immutable, deterministic evidence records with exact source spans, subject relationships,
explicit requirements/preferences/prohibitions/preservation intent, and ambiguity or unresolved
wording. Reviewed Domain Dictionary terms are normalized, and an explicitly supplied compiled
Knowledge Library may contribute its versioned terminology mappings. Only facts directly expressible
by Parser Proposal v1 receive a `CandidateUpdate`; repeated side-stone facts, component-specific
metal, negative constraints, and preservation intent remain structured evidence until a later Matrix
integration can bind them safely. The function never changes Product State, creates side-stone
groups, accepts recommendations, invokes a provider, or requires an ACTIVE production catalog.

Halo constraints recognize bounded EN/RU and mixed-language prohibitions, including
"do not add/include/use", "don't want", "never add", "не добавлять" and "без гало".
The complete negative span protects against an embedded positive match; a separate positive
halo instruction remains evidence. Negated removal ("do not remove the halo") is not treated
as a prohibition of halo presence. Contradictory same-message instructions are not resolved by
inventing precedence; existing final-snapshot conflict validation remains authoritative.

The bounded Owner-approved P0-10 T10-10 binding recognizes the exact RU surface
`асимметричное` and EN `asymmetric` / `asymmetrical` only with an adjacent explicit
product/composition referent and the scoped v1.1 Knowledge record graph. It emits
ordinary structured evidence (`semantic_subject=composition.symmetry_mode`), not
a new legacy `ParserTarget`. The API consumer re-verifies the evidence against the
pinned runtime before proposing the approved `asymmetrical` value to Matrix/Policy.
Negation, uncertainty, recommendations and competing symmetry evidence cannot
become a positive canonical fact. Style labels alone provide no symmetry inference.
The exact T10-10 preservation phrase is evidence, never implicit confirmation or LOCK.
See the [scoped integration decision](../../docs/adr/0035-knowledge-v1-1-session-integration.md).

Iterative Editing v1 accepts a bounded `dimensions_scale` candidate for
`center_stone.dimensions`. It applies the factor only to an existing known dimensions value;
missing values produce a typed issue and locked values retain the existing lock-conflict behavior.
All omitted fields remain model-equal to the current design.

See the [Parser Proposal v1 specification](../../specs/parser/README.md). Install and test from the
repository root:

```sh
python -m pip install -e './packages/domain[test]'
python -m pip install -e './packages/parser[test]'
python -m pytest -c packages/parser/pyproject.toml packages/parser/tests -q
```
