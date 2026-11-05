# KLIB-PE-PREPROD-001: recoverable text-only integration candidate

This is a **preprod candidate awaiting coordinator review**, not a deployed release
or independent functional acceptance. It uses the complete recoverable components
under their existing contracts; it does not claim recovery of the entire historical
P0 authoring workstream.

| Component | Identity | Records | Existing consumer |
| --- | --- | ---: | --- |
| Semantic | `jewelai.preprod.recovered_core/1.0.0`, contract 1.1.0 | 392 | Parser evidence, Policy/Matrix, enrichment |
| Parametric | `jewelai.production.parametric_gemstones/1.0.0` | 584 | `select_parametric_references`, non-authoritative IFP references |
| Dictionary | artifact 1.0.0 | 21 | Existing deterministic ParserProposal normalization |
| Questions/Rules | 2.0.0/2.0.0 | Not comparable to content counts | Existing F workflow |

987 primary original records = 382 semantic + 584 parametric + 21 Dictionary.
The ten already approved P0-10 additions make 997 integrated source records, **not
997 semantic records**. The 1,240 recovery-register rows and 7,085 historical evidence
occurrences are different inventories. No occurrence count creates professional facts.

The semantic release changes only the package/version of the existing reproducible
`jewelai.draft.recovered_core/0.2.0` candidate; all 392 records, IDs and lifecycles
are retained. Its original DRAFT and old 0.1.0 BLOCKED report are not overwritten.
Dictionary `proposed_pending_domain_review` and parametric contract defaults remain
unchanged. This is internal source recovery and integration, not new factual review.
All 584 raw parametric records omit an explicit `review_status`; their existing
typed v1.0 runtime supplies its declared REVIEWED default. Source bytes are not
rewritten or relabelled. Typed consumer compatibility is not presented as a fresh
record-by-record professional approval or normative raw-JSON-schema review.

## Reproduce the existing boundaries

Use the Owner-private original recovery register (SHA-256
`a47e93d9d3860ab54fdd4ee36bc7ff95bc39ad1821ad5830d8ed2ef98c8eaed4`).
Do not commit that private archive. `prepare_preprod_integration.py` verifies every
original record and source-file SHA in **all three contracts** and creates a new
isolated staging directory. Without `--validation-report` it cannot emit ACTIVE.

```sh
python tools/knowledge/prepare_preprod_integration.py \
  --recovered-records /private/recovered-records.json --output /private/new-staging
```

The supplied report uses the **existing** ADR 0028 six-category contract on the new
exact runtime hash. Categories describe actual bounded checks, including the actual
213 semantic language mappings, original provenance, canonical LOCK/group guards
and real Matrix/parametric integration. They do not count synthetic small catalogs
or claim live HTTP/IdP verification. Persisted real-catalog HTTP tests separately
exercise EN/RU/mixed, actual clarification, KEEP/correction, restart, IFP4, exact
7×5 mm/1ct oval-diamond references and truthful unsupported input. Local authentication
uses the existing fake verifier, never real Identity Platform credentials.

With the separately reviewed exact report, existing `promote_knowledge_runtime_v1_1`
and `load_active_runtime` verify the ACTIVE envelope; no gate or public DTO changes.
`verify_preprod_integration.py` then independently verifies that the actual API image's
Dictionary, parametric, roles, rules/questions and prompt bytes match the operational
integration manifest. The manifest is deployment evidence, not a new session contract.

```sh
python tools/knowledge/prepare_preprod_integration.py \
  --recovered-records /private/recovered-records.json --output /private/new-qualified \
  --validation-report docs/prompt-enrichment/preprod-knowledge/validation-report-1.0.0.json
python tools/knowledge/verify_preprod_integration.py /private/new-qualified --repository-root .
```

## Gaps remain explicit

- P0-12 original approximately 50 error-class definitions remain unrecovered. These
  belong to future Visualization Verification, not 50 missing Dictionary translations.
  No replacement taxonomy was authored or needed for this text-only integration.
- There is no exact enumerated source list establishing another “50 missing words”.
  Missing words cannot be reconstructed from the error-class count.
- `round` exists as real semantic evidence (`LANG-EN-ROUND`) but has no executable
  entry in the existing 21-entry Dictionary. It remains structured evidence, without
  silently becoming a canonical shape. The HTTP parametric path uses supported
  `oval` and exact 1ct context; adding a round binding is not disguised as recovery.
- Other unapproved P0-10 mappings remain non-executable. Full original P0 content
  approval, universal language understanding and arbitrary quantitative inference
  are not claimed.

## Preprod delivery — opt-in, no additional runtime IAM

After independent review/merge, publish the seven-file qualified archive to an
immutable private object under
`gs://mmjewellai-preprod-tfstate/knowledge-releases/preprod/` using generation-match0.
The archive contains only the semantic store's four JSON files, `active.json`,
`validation-report.json` and `integration-manifest.json`; other catalogs remain in
their existing exact image paths. They are verified together during the build.

Set preprod Environment variable `PROMPT_ENRICHMENT_RELEASE_JSON` to the exact
`package_id`, `artifact_version`, `contract_version`, `runtime_sha256`,
`validation_report_sha256`, `object`, `object_generation`, `object_sha256` tuple.
It contains no credentials. Empty configuration preserves disabled behavior.

The existing preprod workflow downloads only that private prefix, checks generation
before/after and SHA-256, rejects unexpected/traversing/duplicate archive entries,
and builds a **preprod-only overlay** on the unchanged shared API image. Verification
runs inside the actual image. Files are root-owned/readable by the existing non-root
runtime user. The immutable private GCS object and digest-addressed Artifact Registry
image retain the durable source; the API needs no state-bucket credentials or IAM
grant and has no Drive/network fallback or mutable Knowledge publication path.

Terraform supplies the existing eight release values plus explicit enablement and
the accepted F profile. The entire selection JSON joins both plan/apply configuration
fingerprints. WIF, exact SHA, saved binary plan, checksum/generation binding and
apply-without-replanning remain intact. Production workflow/Terraform/shared Docker
files, providers and worker configuration are unchanged. Rollback clears this new
preprod variable through the same reviewed deployment process; it must retain the
immutable source/evidence needed by already pinned sessions, not rewrite bindings.

No Full Regression, new permanent CI exception or deployment is implied by these
commands. New `tools/knowledge`/report impact can fail existing risk routing closed;
report that gate separately instead of modifying CI to turn it green. Hosted checks,
coordinator review/merge, Terraform plan review and real IdP/browser verification
remain separate delivery gates.
