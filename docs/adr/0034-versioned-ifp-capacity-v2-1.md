# ADR 0034 — Versioned IFP capacity 2.1 (KNA2-004)

Status: Owner-approved bounded direction; implementation awaiting independent review.
Date: 2026-10-29. Existing issue: [#118](https://github.com/mlevin09/mmjewelai/issues/118).

## Context

On ad7de376, current structured enrichment 1.3 no longer calls the legacy compiler. A real
session using Schema 1.1 Product State and Knowledge Library 1.0 still failed during final assembly:
three metal components and one decorative element, with actual Rules READY, rendered 21,162
characters / 21,164 UTF-8 bytes in EN and 20,880 / 23,874 in RU. The 20,000-character IFP limit
raised preparation_capacity_exceeded. No Knowledge Library 1.1 integration is needed to reproduce.

This is distinct from the frozen CompiledPrompt 1.0 limit of 2,000 characters. Raising global
Domain Text or changing already-issued 2.0 validation would break unrelated/historical contracts.

## Decision

Current assembly selects CanonicalInternalFinalPromptV2_1 and CanonicalFinalPromptAssemblyV2_1.
The handoff is CanonicalInternalFinalPromptHandoffV2_1. Both IFP and handoff have schema_version
**2.1.0**. IFP text is bounded to **32,000 Unicode characters / 128,000 UTF-8 bytes**; overflow
fails closed, without truncation or omission. The deterministic formatter retains all original
facts, locks, provenance, disclosures and constraints; only the version heading changes.

The existing CanonicalInternalFinalPrompt / CanonicalInternalFinalPromptHandoff remain exact
**2.0.0** readers, with their original 20,000-character validation. Public
decode_canonical_internal_final_prompt(value) and decode_canonical_handoff(value) accept a model,
JSON-compatible object, JSON string or bytes and dispatch by an explicit schema_version
discriminator. Missing, unsupported or mixed versions and tampered payload/hash fail. No latest
selection, relabeling or validation-fallback probing exists. The builder dispatches assemblies by
their embedded IFP version. Hash algorithms and canonical JSON rules are unchanged.

R1 hardening checks the original parsed mapping before TypeAdapter validation: raw handoffs
must explicitly supply matching outer, nested-reference and nested-IFP schema versions; standalone
raw IFPs must supply their version. Only 2.0.0 and 2.1.0 are accepted. Dict, JSON string and UTF-8
bytes follow the same rule; model defaults cannot repair incomplete wire input. Already validated
typed objects are dumped with their resolved fields before this check, preserving historical
in-memory construction with default versions. Frozen model definitions/schemas and hashes remain
unchanged. Semantic rendering and preparation construction share these guarded readers.

Historical CompiledPrompt 1.0, enrichment 1.2, current structured enrichment 1.3, description 1.0,
release pins and Product State are unchanged. Description retains its independent **20,000 /
80,000** limits. The preparation renderer also retains **20,000 / 80,000**, source+gate retains
**1,048,576 bytes**, and the artifact retains **2,097,152 bytes**. Preparation 1.0 gains an exact
discriminated source reader for 2.1 alongside 2.0; retained 2.0 artifact bytes/hashes, readback and
idempotent replay are unchanged. No table, migration, provider/worker or dispatch changes occur.

Knowledge Library remains an independent reusable component. All 166 governed / 148 Product State
families remain untouched. This is not full Schema/Knowledge Library 1.1 capacity qualification.

## Operation boundaries

An initial enrichment operation atomically retains its optional revision, release pin, complete
cycle and clarification plan before assembling its workflow response. These valid commits are not
corrupt partial IFP writes and are not rolled back by a later capacity failure. The persisted raw
Message also remains the provenance source. No cross-operation transaction contract is introduced.

Final-output/handoff construction and current-state retries are read-only. Overflow returns no
successful partial artifact, changes no canonical state and creates no additional cycle. Repeating
the initial command after its first cycle was committed retains the existing typed conflict rather
than creating a duplicate. A preparation POST still builds/validates its source inside the existing
authorized, CAS-bound transaction: capacity failure leaves neither preparation nor command row.
Earlier valid revisions/cycles/clarification decisions are retained. No authorization/CAS change.

## Alternatives and consequences

- Raise global Text or mutate 2.0: rejected; historical and unrelated semantics would change.
- Truncate, summarize or prune professional state: rejected; authoritative content must survive.
- Increase description/execution limits too: rejected; independently unapproved and unnecessary.
- Move rendering before all earlier commits: not selected; that would change operation semantics.

Current derived IFP/handoff hashes change with the explicit new version; historical artifacts are
never backfilled or rerendered. Reader-compatible rollout remains necessary. Larger valid designs
may still exceed bounded capacity; synthetic exact-boundary tests are not professional qualification.
No real release activation, preprod verification, merge or deployment is implied by unit tests.

## PCAP acceptance trace

| Case | Executable evidence |
| --- | --- |
| PCAP-001 | test_legacy_exact_serialized_golden (four original CompiledPrompt fixtures) |
| PCAP-002 | Existing Schema 1.1 small compilation/projection compatibility tests |
| PCAP-003 | test_ready_session_preserves_complete_state_and_retries_without_new_cycles: 2/3 components, EN/RU |
| PCAP-004 | Same session test and existing stable-alias/collection tests: stable IDs/decoration retained |
| PCAP-005 | Same session test: complete value/origin/confirmation/LOCK projection equality |
| PCAP-006 | Existing Derived/Assumed/disclosure and final-prompt tests, now with current 2.1 writer |
| PCAP-007 | Existing Unknown/NotApplicable and unresolved-detail tests |
| PCAP-008 | test_ifp_capacity_failure_rolls_back_only_the_preparation_operation; retained earlier-commit test |
| PCAP-009 | Exact boundary/UTF-8 tests and repeated/restarted session handoff equality |
| PCAP-010 | Strict version/tamper tests, frozen 2.0 schema fingerprints, current schema drift |
| PCAP-011 | Retained 2.0 preparation GET/replay and historical enrichment-history restoration tests |
| PCAP-012 | Real READY session plus exact 32,000-character validated IFP/handoff |
| PCAP-013 | Independent description/execution limits and old/new semantic-render equality |
| PCAP-014 | 32,001 rejection, independent byte guard, no partial successful handoff |
| PCAP-015 | Missing/unknown/mixed version and hash/payload tamper negatives |
| PCAP-016 | Existing tenant/CAS/authority tests unchanged; no source inference or catalog modifications |
