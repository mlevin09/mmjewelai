# Asset Access contract v1.0.0

Asset Access v1 defines provider-neutral, temporary read access to one validated `ready` Asset. The
default lifetime is 300 seconds and the absolute v1 maximum is 900 seconds. Expiration is computed
from a server clock; callers cannot submit an absolute expiration. The result permits `GET` only and
requires HTTPS.

Before signing, the access operation validates the Asset contract, requires `ready`, and rechecks the
canonical organization/project/asset/content-type object key. `pending`, `failed`, noncanonical, and
out-of-policy requests fail before the signer is called.

The signed URL is an ephemeral bearer secret. It is not Asset metadata, is not persisted, and must
not be logged. This contract does not expose an HTTP endpoint; authenticated membership and
authorization must exist before FastAPI can issue signed access.

```sh
python -m jewelai_assets.access_schema specs/asset-access/schema.json
python -m pytest -c packages/assets/pyproject.toml packages/assets/tests -q
```
