# JewelAI V2 contributor instructions

Read ARCHITECTURE.md, docs/architecture/REPOSITORY_AUDIT.md, relevant specs and ADRs before editing.
- Verify the live remote jewelai-v2 HEAD, working tree, relevant PRs and dependencies before work. Base feature branches and PRs on jewelai-v2; preserve main, archive/v1 and legacy-v1 and never rewrite their history.
- Implement the whole approved functional outcome, not isolated symptoms. Development owns investigation, technical decomposition, implementation, relevant tests and one coherent Draft PR; do not require a new Owner prompt for each technical subtask. Stay within the approved block; report unrelated defects without silently expanding scope.
- Existing root README, Docker and Python packaging describe V1. Do not treat their implementation claims as verified or silently replace them.
- Record architectural changes in docs/adr with context, decision, alternatives and consequences.
- Target FastAPI, PostgreSQL, SQLAlchemy/Alembic, GCS assets and a provider-neutral Model Gateway. Introduce dependencies only with a written justification.
- Keep domain and question selection deterministic. Prompts and LLM responses cannot define business rules or overwrite locked fields.
- Use versioned schema, dictionary, role, question, rule and prompt artifacts with provenance. Do not invent factual gemstone dimensions.
- Keep secrets and customer assets out of Git. Store image bytes in object storage, metadata in PostgreSQL.
- New executable behavior requires meaningful unit tests, including negative cases. Documentation-only changes require link/content and diff checks, not an invented application test result.
- Summarize changed behavior, validation and remaining limitations in each PR. Request domain review of jewelry terminology and assumptions before publishing production catalogs.

## Functional workflow and routing

- For functional implementation, load [jewelai-functional-development](.agents/skills/jewelai-functional-development/SKILL.md). For independent review, regression verification or functional acceptance, load [jewelai-functional-acceptance](.agents/skills/jewelai-functional-acceptance/SKILL.md) in a separate reviewer session. Development cannot certify its own independent acceptance.
- Before coding, establish expected user outcomes, the complete affected journey and cross-feature invariants. Preserve source-backed facts, object ownership, LOCK/KEEP, confirmed values, authority, immutable history and provenance. Never invent professional facts, silently accept recommendations or reinterpret an unresolved conflict.
- Independent acceptance inspects actual code, observable behavior and fresh GitHub CI on the exact reviewed HEAD. Developer-reported PASS and green CI are not functional acceptance. Keep implementation, independent acceptance, merge and deployment statuses distinct.
- Escalate new public/durable contracts, migrations, significant semantic/architectural decisions, release activation and deployment to Owner unless explicitly approved in the current task. State the exact missing decision and evidence; do not invent policy or repeat routine start approval.
- Standard merge requires independent coordinator review and fresh exact-head CI. Codex Development and Acceptance must not self-merge, enable auto-merge or deploy. Submit Draft PRs and leave merge decisions to the independent coordinator under the working protocol.

## Current Prompt Enrichment completion boundary

The active program is TEXT-ONLY: raw user text → internal Parser → Dictionary / Knowledge → Matrix / Rules → canonical Product State → clarification / correction / re-enrichment → readable jewelry description → provider-neutral Internal Final Prompt. Structured Product State and versioned enrichment state remain authoritative; first-pass understanding belongs to JewelAI. Image generation/editing, provider adapters, workers and B3/B4 are outside this completion scope.

Follow the single live backlog order C0 → C1 → F01–F07 and its acceptance gates, rather than treating older foundation-only instructions as current delivery limits. Known professional Knowledge content gaps are Owner-deferred: preserve existing records and historical decisions; do not initiate a new catalog audit, rewrite, requalification or release. TEST-ONLY bindings do not qualify or activate professional Knowledge.

Authoritative working references (read current contents; historical status is not live evidence):

- [Working protocol](https://docs.google.com/document/d/1gVVHWON3wE1WGTsw9LXoDdO2xAMFF58aats9ROtSiAc/edit).
- [Single live Feature Backlog Progress](https://docs.google.com/document/d/168r6pekANdZZjymQpGTIkP_3qv53VqAMSGSw9uxDbfg/edit): the only progress tracker; do not create a parallel backlog. Report evidence for its authorized update without marking unverified work accepted.
- [Approved Boundary Contract](https://docs.google.com/document/d/1TlwnXeWs9lGfARlH7C3e4ji5sT3B0jBXubsB-YKhVN0/edit) and [current prompt contracts](specs/prompts/README.md).

If a source is inaccessible, state the exact limitation and use only verified requirements; never claim to have read it. Preserve credentials and private user content in all evidence. Use existing test infrastructure: no real provider calls or live resource mutations without explicit authorization; no destructive database tests until the existing disposable-PostgreSQL safety gate independently verifies the target.
