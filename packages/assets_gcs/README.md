# JewelAI GCS Assets adapter

`jewelai-assets-gcs` is the production Google Cloud adapter for the provider-neutral contracts in
`jewelai-assets`. It uses `google-cloud-storage>=3.4,<4` because the standard library cannot perform
GCS generation-precondition writes or V4 URL signing. The core Assets package remains cloud-neutral.

The adapter receives an explicit existing bucket name and optional GCP project ID. When a client is
not injected, it constructs `storage.Client` with Application Default Credentials. Production should
use workload/service-account identity; no credential JSON or private key belongs in JewelAI models,
configuration, requests, persistence, or Git.

Writes use `if_generation_match=0`. If that precondition reports an existing object, the adapter
reads metadata only and accepts the retry only when object name, MIME type, byte size, and custom
`jewelai-sha256` metadata all match. It never overwrites, downloads for comparison, changes ACLs,
creates buckets, or returns a public URL.

The signer creates V4 HTTPS `GET` URLs for the exact configured bucket and canonical Asset key.
Credentials must support Google signing. Signed URLs are ephemeral bearer secrets and must not be
logged or persisted. There is deliberately no signed-access FastAPI endpoint before authentication.

Conceptual runtime permissions are limited to `storage.objects.create` and `storage.objects.get` in
the configured bucket, plus an appropriate Google-supported signing capability (for example
`iam.serviceAccounts.signBlob` through an intentionally configured signing identity). Do not grant
public bucket access, project Owner, or broad Storage Admin solely for this adapter. Bucket/IAM
provisioning is outside this package.

```sh
python -m pip install -e './packages/assets_gcs[test]'
python -m pytest -c packages/assets_gcs/pyproject.toml packages/assets_gcs/tests -q
python -m ruff check packages/assets_gcs
python -m ruff format --check packages/assets_gcs
```
