# JewelAI Assets

`jewelai-assets` is the provider-neutral private binary-ingestion boundary. It validates bounded PNG,
JPEG, and WebP bytes by signature, computes authoritative SHA-256 and size metadata, builds a
server-owned tenant/project/asset object key, and coordinates durable `pending → ready|failed`
metadata with a create-only `PrivateObjectStore` port.

The package depends only on Pydantic and the Python standard library. It has no SQLAlchemy, FastAPI,
Model Gateway, provider, network, or cloud SDK dependency. No production object-store adapter is
registered; tests supply an in-memory fake only.

```sh
python -m pytest -c packages/assets/pyproject.toml packages/assets/tests -q
python -m jewelai_assets.schema specs/assets/schema.json
python -m ruff check packages/assets
python -m ruff format --check packages/assets
```
