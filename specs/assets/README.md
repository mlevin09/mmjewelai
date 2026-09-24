# Asset contract v1.0.0

Asset v1 distinguishes reference and generated JewelAI-owned binary metadata from canonical design
state, immutable prompts, generation attempts, and external provider output descriptors. Supported
content types are `image/png`, `image/jpeg`, and `image/webp`; the declared type must match a bounded
signature check. The default technical limit is 20 MiB. SHA-256 and byte size are computed from the
actual bytes.

Object keys are generated as
`organizations/{organization_id}/projects/{project_id}/assets/{asset_id}/original.{ext}`. They never
contain caller filenames, URLs, queries, or arbitrary path segments. Object keys are internal and are
not part of public API responses.

Ingestion persists pending metadata, performs a create-only private object write, verifies returned
metadata, then transitions to ready or a typed failed state. PostgreSQL and object storage are not a
distributed transaction; a crash can leave a pending row for future reconciliation. Reconciliation,
retention/deletion, transformations, production GCS, provider output transport, uploads/downloads,
and signed access are deferred.

```sh
python -m jewelai_assets.schema specs/assets/schema.json
python -m pytest -c packages/assets/pyproject.toml packages/assets/tests -q
```
