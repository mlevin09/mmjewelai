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
jewelry referent and the scoped v1.1 Knowledge record graph. It emits
ordinary structured evidence (`semantic_subject=composition.symmetry_mode`), not
a new legacy `ParserTarget`. The API consumer re-verifies the evidence against the
pinned runtime before proposing the approved `asymmetrical` value to Matrix/Policy.
Negation, uncertainty, recommendations and competing symmetry evidence cannot
become a positive canonical fact. Style labels alone provide no symmetry inference.
The exact T10-10 preservation phrase is evidence, never implicit confirmation or LOCK.
The referent must be jewelry-specific (for example, ring or jewelry design);
generic design/composition and their Russian equivalents are insufficient.
Website/photograph context remains deferred even if a jewelry word also appears.
The scoped recognizer checks both sides of the phrase using explicit `.?!;`
statement boundaries. Line breaks remain formatting inside a continued statement;
the original string and source offsets are never normalized or rewritten.
The existing lexical extraction path (special constraints and Dictionary/Knowledge
matches) is reused to identify negative objects, including multiword dictionary
objects. Unknown objects retain their negative operator as an unclosed scope;
this does not assign a canonical target or invent a prohibition for them.
Before excluding a property prohibition from symmetry analysis, the entire remaining
operator scope must close: only complete existing instructions with their own
operator and supported clause separators may follow it. Comma/newline-separated
bare objects, alternatives and unknown list members do not prove closure. The
operator is retained and symmetry deferred; matched terms in the unclosed tail
remain evidence without positive parser updates. This includes other dictionary
fields, so rejected list members cannot silently become Product State facts.
An independent closed `no halo`/`without engraving` still permits positive symmetry
and valid KEEP. Unknown noun compounds after a product word are deferred instead
of expanding a non-jewelry noun blacklist. Only a complete approved preservation
instruction with positive governing context is exempted from rejection.
An unrelated unresolved list cannot poison a positive requirement in another
terminated sentence, in either order. A negative reference to the **same** property
still blocks it across sentences; nominal mentions are blocking evidence only,
not additional positive Knowledge bindings. Unclear mixed scope is not
applied. For example, `No halo\nAn asymmetric ring.` without punctuation and
`An asymmetric ring, no halo or side stones.` remain non-applied rather than guessing
the boundaries of an unsupported negative list.

F00 acceptance tests exercise representative positive, rejected, uncertain,
coordinated, multiline/non-jewelry and KEEP inputs through actual HTTP, three
cycles, correction, clarification, revision/CAS, immutable binding and restart to
IFP 2.1. Trace output reports actual candidates/dispositions, initial Matrix
decisions, canonical symmetry, final description, unresolved targets and IFP facts/KEEP.
Accepted symmetry requirements retain their original candidate/span/Message evidence
as canonical-bound requirements, rather than contradictory unresolved constraints.
When the same message also supplies the approved KEEP, that preservation instruction
explicitly supersedes the requirement evidence; both records remain queryable.
Across corrections, a canonical requirement that reaffirms the preserved value is
covered by the active KEEP, rather than revoking it. Compatibility compares actual
canonical values in the KEEP's immutable source revision and the current revision;
historical reads stay organization/session scoped. The KEEP retains its exact ID,
hash, wording and source. A new explicit KEEP can supersede it under the existing
same-kind authority; uncertain or unsupported cancellation/conflict text cannot.
This adds no cancellation action or intrinsic LOCK. Missing/mismatched historical
source evidence fails closed instead of guessing compatibility.
Active explicit KEEP is shown once in the user-readable description as well as
the structured IFP. Superseded/rejected evidence and implicit LOCK renderings do
not create duplicate preservation instructions in the description.
Genuinely unresolved intent is retained. The release is explicitly
test-only; this is not professional catalog qualification or preproduction evidence.
The final description renders the accepted canonical symmetry in RU/EN, without
inventing that fact when it is absent. Provider-facing facts remain canonical.
If a separate unresolved request concerns an accepted target, its exact evidence
is still shown as an unresolved **request**, rather than an ambiguous canonical fact.

Reproduce F00-R1/R2/R3 and additional controls with:

```sh
python -m pytest -c packages/parser/pyproject.toml packages/parser/tests/test_p010_symmetry.py -q
python -m pytest -c apps/api/pyproject.toml apps/api/tests/test_p010_symmetry_runtime.py -q -s
```

`F00_TRACE` uses synthetic messages and reports the actual three-cycle HTTP lifecycle;
the same cases run against independently verified disposable PostgreSQL in Runtime API CI.
Independent read-only functional acceptance on the final PR head remains a separate gate.
See the [scoped integration decision](../../docs/adr/0035-knowledge-v1-1-session-integration.md).

Core intent handling uses the same bounded statement/clause context for polarity,
certainty and component ownership. General classification, ownership and the
symmetry scope guard share one negative-operator vocabulary, including auxiliary
and contraction forms. Recognized trailing rejection cannot create a
positive requirement; tentative Dictionary terms and special instructions remain
ambiguous evidence. Independent statements and explicit contrast clauses retain
their own facts. A comma after a hedge or within its list does not grant fresh
explicit authority. A later negative component mention cannot steal an earlier
positive object's ownership. Decimal measurements retain their original spans.
The existing unclosed-negative-list guard runs independently of optional P0-10
membership; only the actual symmetry value binding requires that approved content.
These corrections introduce no conflict-resolution, cancellation, Unknown, group
creation or component-ID policy. Existing canonical EDIT/CAS, confirmation and
LOCK/KEEP authority remain unchanged. Readable output also renders the existing
accepted `style_descriptors` fact via the current Dictionary/value presenter.

Independent request/rejection predicates also delimit conjunction and newline
scope. `I want gold and I do not want platinum` preserves positive gold; the
reverse order does too. A bare coordinated object list retains its shared
governor: `Gold and platinum is not what I want` rejects both. The same original
offset boundaries govern polarity, certainty, component ownership and closure of
negative lists. A bare object after `no halo, ...` does not gain positive authority
merely from a comma or `and`. Postfix rejection remains supported. This is bounded
deterministic language support, not a general grammar or a conflict winner policy.

Existing Russian `хочу` remains a preference. Material preferences are retained
as evidence; the current Question Catalog has no `metal.material` acceptance
question. An explicit supported correction such as `Кольцо из золота` can apply
gold through the existing revision boundary. This correction does not silently
accept a preference or add a new clarification contract.

```sh
python -m pytest -c packages/parser/pyproject.toml packages/parser/tests/test_core_intent_scope.py -q
python -m pytest -c apps/api/pyproject.toml apps/api/tests/test_core_intent.py -q -s
```

`C1_TRACE` records synthetic raw input, observed candidates/dispositions/Matrix,
canonical before/after, release identity and description/IFP. The six-cycle tests
also check an authorized correction, clarification, immutable history, stale CAS,
tenant isolation and fresh-application restoration. The same C1 scenarios reuse
the existing independently verified disposable-PostgreSQL fixture in CI. These
are development observations, not independent acceptance or a real release.

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

## F01 text understanding and object ownership

Nominal object scope and intent scope are separate. `and` can coordinate two
objects under one predicate; it is not automatically a new positive assertion.
Named product/component/center/side anchors and connectors resolve the local
owner without allowing a nearby prong/shank to steal a product-body fact.
Coordinated modifiers such as `white and yellow gold prongs` share their later
owner; a conjunction between modifiers does not create a new body-metal scope.
Hyphenated spellings reuse existing Dictionary surfaces (including compound
metal colors), while material/color remain distinct properties with original
source spans. Construction adjectives such as `split-shank ring` are not evidence
that the preceding metal belongs only to a shank component.

| Surface | Current recognition/application boundary |
| --- | --- |
| Product | Existing Dictionary ring/pendant terms and RU inflections → existing `jewelry_type` proposal |
| Body metal | Existing gold/platinum and white/yellow/rose vocabulary → independent material/color proposals |
| Named component metal | Band/prongs retain their existing subjects; head/basket/etc. retain source labels with UNKNOWN typed subject when no enum exists. **No global metal target or update**, no component ID inference, even if a component already exists |
| Center stone | Dictionary diamond/emerald, oval/emerald-cut, brilliant/step cut, supported setting and explicit stone measurements → existing typed proposals, subject to certainty, LOCK and canonical transition |
| Side stones | Preserve material/shape/cut/measurement owner evidence. Only existing quantity binding may address one existing group; no group creation or material/shape fallback to center, including when zero/multiple groups exist |
| Style | Existing Dictionary style target; component-specific style is not silently promoted to overall style |
| Finish/color/orientation/construction | Recognize available supplied Library mappings of any kind and existing Dictionary construction vocabulary. Unbound kinds have no invented canonical target; unknown wording retains local owner and source. Schema field existence alone grants no parser authority |
| Purity | Typed structured ParserCandidate purity exists, but the full-message StructuredTarget/binding is absent. Preserve source wording; no karat/fineness conversion or implicit alloy |

Library recognition cannot create accepted requirements without an approved
binding. Longest-match suppression is source-local and preserves independent
material inside an approved compound metal-color term; it still does not turn
`emerald-cut diamond` into emerald material. Deduplication includes semantic
subject so generic recognition cannot erase an approved explicit binding.
Measurements share the same certainty/negative governance and cannot become
center-stone updates when explicitly attached to a component.

The controlled API retains unapplied source-backed requirements through the
existing unresolved constraint-evidence DTO and original Message. The source
citation uses the original nominal phrase, distinguishing `gold prongs` from
accepted body gold; matched Parser spans remain unchanged. Accepted equivalent
Dictionary/approved-binding evidence is not labelled unapplied. Existing
clarification-plan/answer lineage continues to own supported ambiguity; preferences
are not converted into requirement evidence. The review description quotes
unapplied source wording separately from canonical facts, without internal IDs or
raw JSON. This introduces no new DTO, target enum, conflict resolution, history
rewrite or Knowledge activation.

Expanded canonical bindings still require an Owner decision on versioned targets,
value types and stable identity resolution (Issue #120); conflict resolution,
Missing/Unknown and professional rules remain #121/#124/#122 scopes. Russian
`хочу` remains a preference and no material ACCEPT question is invented.

```sh
python3 -m pytest -c packages/parser/pyproject.toml packages/parser/tests/test_f01_ownership.py -q
python3 -m pytest -c apps/api/pyproject.toml apps/api/tests/test_f01_ownership.py -q -s
```

`F01_TRACE` and the existing detailed `C1_TRACE` expose synthetic raw input,
release identity, candidate/disposition/Matrix, canonical state and final output.
PostgreSQL counterparts use the existing independently verified disposable fixture;
none of these synthetic tests qualify a professional catalog or live deployment.
