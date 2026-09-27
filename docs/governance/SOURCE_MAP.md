# JewelAI Source Map

Status: Working
Last reviewed: 2026-09-27

## Governance rules

The Drive/Project knowledge corpus is in a Working stage. No Drive/Project source is classified as Accepted merely because it is mature or actively used.

Repository-controlled records retain their own explicit lifecycle. For example, an ADR marked `Accepted` in the repository remains an accepted engineering decision within its stated scope.

Status and authority are separate dimensions. A Working source may be the primary Working reference within a narrow scope without being Accepted.

Authority and freshness are also separate dimensions.

Categories such as Research, Benchmark, Competitor Research, and External Reference describe the nature of evidence; they do not create JewelAI requirements.

External/vendor material may inform JewelAI decisions but cannot establish JewelAI requirements by itself.

## Project knowledge status vocabulary

- Working
- Draft
- Under Review
- Historical
- Superseded
- Archived
- External Reference

`Accepted` for Drive/Project knowledge is reserved until Project-level approval authority and an explicit approval action are defined.

## Live repository sources

| Source | Scope | Authority / use |
|---|---|---|
| Current merged `jewelai-v2` | Implemented V2 behavior | Primary implementation evidence |
| `AGENTS.md` | Contributor workflow | Current repository contributor instructions |
| `ARCHITECTURE.md` | V2 architecture baseline | Repository architecture baseline; inspect status and current implementation together |
| `docs/adr/*` | Durable engineering decisions | Preserve each ADR's explicit repository status; Accepted ADRs are authoritative within scope |
| `specs/*` | Versioned technical contracts | Working/current technical contracts according to repository issue/implementation state |
| GitHub Issues / PRs | Work/implementation history | Current issue/PR truth and review trail |
| CI/CD and runtime evidence | Validation | Current validation evidence |
| Live deployment/infrastructure | Operational state | Operational authority for what is actually provisioned/running |

## Drive / Project source inventory

| Source | Category | Scope | Status | Working authority / use |
|---|---|---|---|---|
| BLNG_Journey_API_RU.docx | External Reference | BLNG journey API | External Reference | Supporting external technical reference |
| BLNG_Documentation_Index_RU.docx | External Reference | BLNG documentation map | External Reference | Navigation/reference only |
| BLNG_User_API_RU.docx | External Reference | BLNG user API | External Reference | Supporting external technical reference |
| BLNG_Official_Documentation_RU.docx | External Reference | BLNG platform documentation | External Reference | Supporting external/product reference |
| BLNG_Billing_API_RU.docx | External Reference | BLNG billing API | External Reference | Supporting external commercial/technical reference |
| BLNG_Technical_FAQ_Michael_Kats_v1.pdf | External Reference | BLNG technical workflows | External Reference | Supporting evidence; does not create JewelAI requirements |
| BLNG_Enterprise_Pilot_Michael_Kats_v1.docx.pdf | External Reference | BLNG enterprise/pilot | External Reference | Supporting business/enterprise reference |
| JewelAI_Stone_Inventory_Module_v1.0.docx | Product Concept | Stone inventory | Working | Product proposal/hypothesis; no priority implied |
| JewelAI_Техническое_описание_v1.2.docx | Technical / Historical | Earlier JewelAI pilot implementation | Historical | Historical implementation context; not current architecture by default |
| JewelAI_CustomerDiscovery_опросник.docx | Customer Discovery | Research methodology | Working | Primary Working methodology reference; embedded hypotheses remain hypotheses |
| JewelAI_TZ_v1.docx | Product / Technical Specification | Earlier broad JewelAI scope | Draft / Historical | Historical planning/specification context; not current requirement set |
| JewelAI_Chinese_AI_API_Benchmark_2026-09-06.docx | Research / Benchmark | Chinese AI/API landscape | Working | Time-bound experimental/research evidence |
| JewelAI_Visualization_Benchmark_Scenarios_v1.3.docx | Benchmark Methodology | Visualization evaluation | Working | Primary Working benchmark methodology; filename/internal-version mismatch should be fixed on next revision |
| JewelAI — Оценка моделей визуализации.xlsx | Benchmark Results | Visualization model evaluation | Working | Time-bound experimental evidence; interpret with methodology/config/date |
| Gemology_Trainer_Description_1.docx | Product Concept | Gemology training | Working | Product proposal/hypothesis; no priority implied |
| AI_Consultant_Description_1.docx | Product Concept | AI consultant | Working | Product proposal/hypothesis; no priority implied |
| Оптимизация работы дизайнеров.doc.docx | Product / Research | Designer workflow optimization | Working | Product/workflow proposal and research context |
| Configurator_Product_Description_1.docx | Product Concept | Configurator | Working | Product proposal/hypothesis; no priority implied |
| Notable Jewelry Visualization Projects | Research / Reference | Jewelry visualization landscape | Working | Supporting research/reference |
| ArtCouncil_Vision_Spec_SKELETON.pdf | Draft Specification | Vision specification structure | Draft | Structural/reference material; not current requirement authority |
| JewelAI — Image API для визуализации украшений (полная версия).docx | Research / Technical Analysis | Image API landscape | Working | Time-sensitive technical research; re-verify current external facts |
| JewelAI_AI_Visualization_Module_v0.3_API_ready.pdf | Architecture / Historical | Earlier visualization architecture | Historical | Earlier architecture reference |
| JewelAI_Retail_Vision_Spec.pdf | Product-specific Architecture | Retail visualization | Working | Primary Working reference within Retail visualization scope; does not imply Retail priority |
| JewelAI_v4.pdf | Architecture / Historical-to-Working Context | Visualization architecture evolution | Historical / Working Context | Important predecessor/context; use newer Working core/product-specific material where scope overlaps |
| JewelAI_Vision_Core.pdf | Architecture | Shared visualization core | Working | Primary Working reference within Visualization Core scope; not Project-level Accepted |
| Маркетингово-технический анализ image generation_editing API для ювелирного B2B2C-продукта.pdf | Research / Technical Analysis | Image generation/editing API market | Working | Time-sensitive supporting research; not requirement authority |
| Обзор приложения Tashviai.docx | Competitor Research | Tashviai | Working | Competitor evidence; does not create JewelAI requirements |
| Обзор приложения jewelerstusio.ai.docx | Competitor Research | jewelerstusio.ai | Working | Image/screenshot-based visual competitor evidence; no extractable document text |
| JewelAI_Ecosystem_Pitch_1.pptx | Business / Presentation | Ecosystem positioning | Historical / Contextual | Presentation evidence; statements such as Retail-first do not establish current priority |
| JewelAI_Product_MVP_1.pptx | Product / Presentation | Earlier MVP framing | Historical / Contextual | Historical product/planning context |
| JewelAI_Дорожная_карта_MVP_2.docx..docx | Roadmap / Planning | Earlier MVP roadmap | Historical / Contextual | Historical planning; useful evidence such as vertical-slice reasoning does not establish current sequencing |
| JewelAI_MVP_0_1_Map_v1.0.xlsx | Planning / Decision History | Earlier MVP map | Historical / Reviewed | 87 historical decision cells reviewed; no automatic migration to current Decision Log; see `reviews/MVP_0_1_DECISION_REVIEW.md` |

## Working source-of-truth guidance

### Current implementation
Current merged repository → tests/runtime evidence → deployment/infrastructure configuration → current technical documentation → historical technical material.

### Architecture
Explicit repository architecture decisions/ADRs according to their status → current primary Working architecture specifications within their scope → current implementation → exploratory/historical architecture material.

### Product strategy and priority
Explicit recorded team decisions → validated evidence and current constraints → Working strategy/specifications → proposals/hypotheses → historical roadmaps/presentations.

### External/time-sensitive facts
Verify current authoritative external sources when present-day accuracy matters. Do not use this Source Map as a cache of volatile pricing, model availability, API behavior, competitor functionality, regulation, or cloud limits.

## Follow-up

- Define who may assign Project-level `Accepted` status before using that status for Drive/Project documents.
- Correct the visualization benchmark filename/internal-version mismatch when revising that source.
- Refresh the Project Sources/Drive governance mirror after material governance changes.
