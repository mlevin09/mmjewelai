# JewelAI V2 contributor instructions

Read ARCHITECTURE.md, docs/architecture/REPOSITORY_AUDIT.md, relevant specs and ADRs before editing.
- Work in this existing repository. Base feature branches and PRs on jewelai-v2. Preserve main, archive/v1 and legacy-v1; never force-push these refs.
- This baseline is preparation only. Implement one issue at a time; do not add frontend, image generation, cloud resources or database persistence to domain foundation issues.
- Existing root README, Docker and Python packaging describe V1. Do not treat their implementation claims as verified or silently replace them.
- Record architectural changes in docs/adr with context, decision, alternatives and consequences.
- Target FastAPI, PostgreSQL, SQLAlchemy/Alembic, GCS assets and a provider-neutral Model Gateway. Introduce dependencies only with a written justification.
- Keep domain and question selection deterministic. Prompts and LLM responses cannot define business rules or overwrite locked fields.
- Use versioned schema, dictionary, role, question, rule and prompt artifacts with provenance. Do not invent factual gemstone dimensions.
- Keep secrets and customer assets out of Git. Store image bytes in object storage, metadata in PostgreSQL.
- New executable behavior requires meaningful unit tests, including negative cases. Documentation-only changes require link/content and diff checks, not an invented application test result.
- Summarize changed behavior, validation and remaining limitations in each PR. Request domain review of jewelry terminology and assumptions before publishing production catalogs.
