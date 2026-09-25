# JewelAI Assets

`jewelai-assets` is the provider-neutral private binary-ingestion boundary. It validates bounded PNG,
JPEG, and WebP bytes by signature, computes authoritative SHA-256 and size metadata, builds a
server-owned tenant/project/asset object key, and coordinates durable `pending → ready|failed`
metadata with a create-only `PrivateObjectStore` port. It also defines a separate READY-only,
canonical-key-validated, short-lived `PrivateObjectAccessSigner` boundary.

Generated-output orchestration may call `stage_asset_object` to durably write validated bytes at the
final deterministic private key before run success, then call `finalize_staged_asset` after success
to establish READY metadata without a second storage write. Ordinary reference ingestion continues
to use `ingest_asset` and its existing `pending → storage → ready|failed` behavior.

The package depends only on Pydantic and the Python standard library. It has no SQLAlchemy, FastAPI,
Model Gateway, provider, network, or cloud SDK dependency. The production adapter lives separately in
`packages/assets_gcs`; core tests use in-memory fakes only. Signed access defaults to 300 seconds,
allows at most 900 seconds, requires HTTPS `GET`, and is never persisted.

```sh
python -m pytest -c packages/assets/pyproject.toml packages/assets/tests -q
python -m jewelai_assets.schema specs/assets/schema.json
python -m jewelai_assets.access_schema specs/asset-access/schema.json
python -m ruff check packages/assets
python -m ruff format --check packages/assets
```
