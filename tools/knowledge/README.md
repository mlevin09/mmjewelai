# KNA2-009 partial recovered-core DRAFT

This offline packaging command implements an **explicit shared-record projection**,
not the authentic full P0 v1.1 professional catalog. It preserves the 382 records
in the authenticated later core source (11 Source, 13 Claim, 117 DomainKnowledge,
211 LanguageMapping, 30 Policy), with original IDs, statements, relationships,
targets and lifecycle. No additive v1.1 policy or concept-to-target binding is
created. It cannot repair inaccessible original content.

Source/Claim/DomainKnowledge/LanguageMapping have exactly the same record models in
the two contracts. The projection independently validates both compilers, requires
each unchanged Policy target to be valid in the frozen v1.1 grammar, and checks
field equality for every record. Package identity is intentionally separate:
`jewelai.draft.recovered_core / 0.1.0`, Knowledge contract/schema `1.1.0`.
This is a traceable legacy-content subset permitted by the Phase B assignment;
**it is not evidence of recovered additive v1.1 professional content**.

The code accepts only the SHA-pinned historical source and SHA-pinned complete
recovery register. These pins identify exact bytes, not an automatic source-review
authority. Existing REVIEWED markers are retained, never assigned to missing,
summary-only, new, or supplementary content. REVIEWED is internal curation, not
ACTIVE or approval of this new package.

## Reproduction

Install the repository domain package in an isolated environment. Obtain the
owner-authorized original immutable recovery archive from the existing private
KNA2-009 evidence destination. Do not make that archive public or commit it here.

1. Verify the original artifact manifest and immutable archive member hashes.
2. Extract only `recovered-records.json` from
   `Original_KNA2-009_Output_Immutable.zip` using the standard ZIP API. It must hash
   to `a47e93d9d3860ab54fdd4ee36bc7ff95bc39ad1821ad5830d8ed2ef98c8eaed4`.
3. Run from this repository:

```sh
python tools/knowledge/build_recovered_draft.py \
  --recovered-records /private/evidence/recovered-records.json \
  --output /private/evidence/new-draft-output
```

The output must be a **new isolated directory**, never a live configured artifact
root. The existing `KnowledgeArtifactStoreV1_1.publish()` stages only the four
ADR 0029 artifacts. It never promotes or emits an ACTIVE envelope. Source inputs
are read-only. No network, provider, database, deployment or environment update
is part of this command.

All 1,240 original register rows are retained: 382 included and 858 explicitly
excluded from this projection. Inclusion evidence contains the original JSON
pointer, record, lifecycle, locator and SHA as well as the packaged record.
Exclusions preserve references to the complete unchanged recovery corpus.
`candidate-inventory.json` hashes each output file except itself. Its identity
hashes follow ADR 0029 (canonical JSON without the trailing newline); file hashes
cover actual bytes including the newline. Absolute paths and timestamps are not
part of the reproducible candidate.

The complete original recovery archive preserves all 987 primary repository
records, the 166-family traceability and historical chapters. The 584 parametric
records and 21 Dictionary entries remain in their own contracts. They are not
converted into Knowledge Claims. KNA2-010 numeric provenance is not re-approved.
The original P0-10 artifact remains supplementary private evidence: it has no
approved lossless Source/Claim/Policy conversion or target binding here. Original
P0-12 classes and other inaccessible primary artifacts remain explicit gaps.

## Validation and release boundary

`packages/prompts/tests/test_recovered_knowledge_draft.py` exercises this exact
projected core, deterministic compilation, all actual language surfaces, policy
identity/LOCK/group protection, immutable storage, tamper rejection and
qualification refusal. Test-only hostile proposals and synthetic recovery
mutation inputs are not candidate records or qualification evidence.

Record actual six-category evidence for the candidate's exact runtime hash.
Compiler, matcher and bounded generic policy tests can pass independently of
full professional provenance/behavioral acceptance. Missing original corpus
linkage, missing approved additive policies, and missing authentic semantic
regression cases must not be converted into PASS.

No all-PASS report or ACTIVE envelope is manufactured for this candidate.
`qualify_knowledge_release_v1_1()` must reject it without ACTIVE evidence. Do not
bypass that rejection to create a session or claim clarification/correction,
restart, immutable binding, or IFP 2.1 acceptance with this actual candidate.
Passing PR #133 synthetic integration tests demonstrates machinery only.

Next gates are independent source/package review and a precise decision about
which original records and approved v1.1 mappings can populate the full catalog,
then real six-category qualification, separately authorized ACTIVE promotion,
preproduction verification and production release. No live request handling,
historical fixture, target registry, contract, migration, provider or deployment
behavior changes in this PR. Issue #125 remains open.

## C2 T10-10 extension (isolated DRAFT 0.2.0)

The subsequent bounded [Owner approval](https://github.com/mlevin09/mmjewelai/issues/125#issuecomment-6502450359)
permits ten traceable P0-10 v1.1 records for T10-10 only. Their checked-in fragment
and record hash/source-pointer register are under `data/knowledge/v1_1/`.
No full private original archive is checked in. Missing IDs use deterministic
P010/C2/semantic-role or locale names; original `asymmetry` and STYLE-10-02/06/07
IDs are preserved. `geometric`, eight unrelated overlapping concepts and
same-URI/different-ID GIA sources are neither imported nor silently reconciled.

```sh
python tools/knowledge/build_p010_symmetry_draft.py \
  --output /private/evidence/new-c2-draft-output
```

This reuses the recovered-core projection, rejects ID collisions in every record
group and stages 392 records as `jewelai.draft.recovered_core / 0.2.0` through the
existing immutable v1.1 store. Output must be a new isolated directory. It creates
no validation report or ACTIVE envelope and never selects a runtime catalog.
The old 0.1.0 candidate/report remains unchanged and cannot qualify the new hash.
The actual extended DRAFT is still BLOCKED for release; synthetic qualified HTTP
fixtures demonstrate machinery only. Full professional provenance/behavioral
qualification and explicit promotion are still required. Issue #125 stays open.
