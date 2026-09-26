# JewelAI GCS Assets adapter

`jewelai-assets-gcs` is the production Google Cloud adapter for the provider-neutral contracts in
`jewelai-assets`. It uses `google-cloud-storage>=3.4,<4` because the standard library cannot perform
GCS generation-precondition writes or V4 URL signing. The core Assets package remains cloud-neutral.

The adapter receives an explicit existing bucket name, optional GCP project ID, and optional
`signing_service_account_email`. The signing email is non-secret configuration used only for
keyless IAM signing. When a client is not injected, the adapter constructs `storage.Client` with
Application Default Credentials. Production should use workload/service-account identity; no
credential JSON, private key, or OAuth token belongs in JewelAI models, configuration, requests,
persistence, or Git.

Writes use `if_generation_match=0`. If that precondition reports an existing object, the adapter
reads metadata only and accepts the retry only when object name, MIME type, byte size, and custom
`jewelai-sha256` metadata all match. It never overwrites, downloads for comparison, changes ACLs,
creates buckets, or returns a public URL.

The signer creates V4 HTTPS `GET` URLs for the exact configured bucket and canonical Asset key. It
supports two credential modes:

- credentials implementing `google.auth.credentials.Signing` sign locally and are passed directly
  to the Storage SDK without an OAuth refresh;
- non-signing workload/metadata ADC credentials are refreshed for a short-lived OAuth token, then
  the Storage SDK receives that token and a validated service-account email so its supported IAM
  `signBlob` path performs signing without a downloaded private key.

For keyless signing, the explicit `signing_service_account_email` takes precedence over an identity
exposed by refreshed credentials. If neither provides a valid `*.iam.gserviceaccount.com` identity,
signing fails closed. The OAuth token authorizes `signBlob`; it is not included in the resulting URL.
Signed URLs are ephemeral bearer secrets and must not be logged or persisted. The authenticated API
integration defined by ADR 0015 now issues them only after current database membership and exact
session/Asset scope checks; ordinary Asset metadata endpoints remain URL-free.

Conceptual runtime permissions are limited to `storage.objects.create` and `storage.objects.get` in
the configured bucket. For keyless signing, enable the Service Account Credentials API, allow the
runtime principal to call `iam.serviceAccounts.signBlob` on the selected signing identity (for
example through Service Account Token Creator or a narrower custom role), and grant that signing
identity the object-read permission represented by the signed URL. Do not grant public bucket
access, project Owner, or broad Storage Admin solely for this adapter. Bucket/IAM provisioning is
outside this package.

```sh
python -m pip install -e './packages/assets_gcs[test]'
python -m pytest -c packages/assets_gcs/pyproject.toml packages/assets_gcs/tests -q
python -m ruff check packages/assets_gcs
python -m ruff format --check packages/assets_gcs
```
