# JewelAI V2 API

This FastAPI application is the first runtime boundary around the deterministic domain package. HTTP
routes call application services; services call `jewelai_domain` transitions and the SQLAlchemy
repository. The domain package imports neither FastAPI nor SQLAlchemy.

## Local setup

Python 3.12+ and PostgreSQL are the production-compatible target:

```sh
python -m pip install -e './packages/domain[test]'
python -m pip install -e './packages/prompts[test]'
python -m pip install -e './packages/model_gateway[test]'
python -m pip install -e './packages/model_gateway_openai[test]'
python -m pip install -e './packages/assets[test]'
python -m pip install -e './packages/assets_gcs[test]'
python -m pip install -e './packages/auth[test]'
python -m pip install -e './packages/auth_oidc[test]'
python -m pip install -e './packages/persistence'
python -m pip install -e './workers/generation[test]'
python -m pip install -e './packages/parser[test]'
python -m pip install -e './apps/api[test]'
export DATABASE_URL='postgresql+psycopg://jewelai:jewelai@localhost:5432/jewelai'
export OIDC_ISSUER='https://identity.example/'
export OIDC_AUDIENCE='jewelai-api'
export OIDC_JWKS_URL='https://identity.example/.well-known/jwks.json'
export GCS_ASSET_BUCKET='jewelai-assets-prod'
# Optional non-secret signing configuration:
export GCP_PROJECT_ID='jewelai-prod'
export GCS_SIGNING_SERVICE_ACCOUNT_EMAIL='signer@jewelai-prod.iam.gserviceaccount.com'
alembic -c packages/persistence/alembic.ini upgrade head
uvicorn jewelai_api.app:create_app --factory
```

`DATABASE_URL` and explicit artifact versions configure the runtime. Sessions persist their schema,
role, dictionary, question, rules, and prompt-template versions at creation; they never follow a
“latest” file.

## API scope

- `GET /health`
- `GET /me`
- `POST /organizations`
- `GET|POST /organizations/{organization_id}/memberships`
- `PATCH|DELETE /organizations/{organization_id}/memberships/{principal_id}`
- `POST /organizations/{organization_id}/projects`
- `POST /projects/{project_id}/sessions`
- `GET /sessions/{session_id}`
- `POST /sessions/{session_id}/messages`
- `POST /sessions/{session_id}/parser-proposals`
- `GET /sessions/{session_id}/revisions`
- `GET /sessions/{session_id}/revisions/{revision_id}`
- `POST /sessions/{session_id}/revisions`
- `POST /sessions/{session_id}/evaluate`
- `POST /sessions/{session_id}/prompt-revisions`
- `GET /sessions/{session_id}/prompt-revisions`
- `GET /sessions/{session_id}/prompt-revisions/{prompt_revision_id}`
- `POST /sessions/{session_id}/generation-runs`
- `GET /sessions/{session_id}/generation-runs`
- `GET /sessions/{session_id}/generation-runs/{generation_run_id}`
- `GET /sessions/{session_id}/assets`
- `GET /sessions/{session_id}/assets/{asset_id}`
- `POST /sessions/{session_id}/assets/{asset_id}/access`

`GET /health` is public. Every product route requires a verified bearer JWT. The JWT establishes an
external identity, which resolves to a JewelAI principal; current database membership authorizes an
organization. Session routes use `X-Organization-ID` only as the requested tenant selector, never as
identity proof. Existing repository scopes remain defense in depth. Conversational roles never
grant permissions, and JWT role/group/organization claims are ignored.

Production startup fails closed unless `OIDC_ISSUER`, `OIDC_AUDIENCE`, and HTTPS `OIDC_JWKS_URL` are
configured. It also requires `GCS_ASSET_BUCKET` unless an Asset access signer is explicitly injected;
`GCP_PROJECT_ID` and `GCS_SIGNING_SERVICE_ACCOUNT_EMAIL` are optional non-secret settings. Google
ADC/workload identity supplies credentials—service-account private-key JSON is not application
configuration. The resource server stores no token or raw claims. Existing pre-auth organizations are
not automatically claimed; any production backfill requires an explicit trusted process.

Runtime timestamps and IDs are server-owned. Transition message provenance is accepted from the
caller and checked by the existing domain model against the server revision timestamp. Evaluation
persists ASK lineage but never applies DERIVE/ASSUME proposals or mutates a revision.

Parser candidates are untrusted structured inputs. The API binds them to a persisted user message,
the session's resolved locale and pinned dictionary, then returns a deterministic proposal. Proposal
creation does not persist a design revision. Clients explicitly submit the proposed design through
the existing EDIT endpoint, where domain validation and database CAS remain authoritative. There is
no provider SDK, LLM call, parser prompt, or automatic acceptance in this slice.

Prompt compilation evaluates the pinned Rules Engine directly and requires `READY` without creating
a question event. It compiles the exact current revision with the session-pinned prompt artifact,
validates the lock manifest/text/hash, rechecks current revision under the persistence transaction,
and writes one immutable prompt revision per explicit successful request. It accepts no caller prompt
text, provider, model, transient knowledge fact, or parameters and performs no provider call.

Generation-run POST accepts only a prompt revision and a server-configured versioned profile ID. It
validates ownership and the stored prompt contract, then creates a pending run; it never invokes a
gateway inline. No generation profile or fake provider is registered by default. Tests inject the
`test_default@1.0.0` profile resolving to `test/deterministic-image-v1` with output count 1. The
one-shot worker is invoked separately, claims atomically, validates untrusted result metadata, and
does not recompile or compare against a newer current design revision. The OpenAI adapter is never
constructed by `create_app()` and no API route invokes a provider. Production composition may inject
it into the worker with environment-managed credentials, bounded timeout, and disabled SDK retries.

Asset list/get endpoints expose scoped metadata only. They omit internal object keys, bytes, buckets,
and URLs. The explicit authenticated `POST .../assets/{asset_id}/access` action checks current
database membership and exact tenant/session/Asset scope, then uses the existing provider-neutral
contract and production GCS V4 signer to return a temporary HTTPS GET capability for a READY Asset.
The default TTL is five minutes and maximum is fifteen minutes. The JSON response is never redirected
or cached (`no-store, private`), and the URL is never persisted. Membership revocation blocks future
issuance but cannot revoke a capability already issued before its expiration. No binary bytes pass
through FastAPI; binary upload, retention, and reconciliation remain unimplemented.

## Verification

```sh
python -m pytest -c packages/parser/pyproject.toml packages/parser/tests -q
python -m pytest -c packages/auth/pyproject.toml packages/auth/tests -q
python -m pytest -c packages/auth_oidc/pyproject.toml packages/auth_oidc/tests -q
python -m pytest -c packages/prompts/pyproject.toml packages/prompts/tests -q
python -m pytest -c packages/model_gateway/pyproject.toml packages/model_gateway/tests -q
python -m pytest -c packages/model_gateway_openai/pyproject.toml packages/model_gateway_openai/tests -q
python -m pytest -c packages/assets/pyproject.toml packages/assets/tests -q
python -m pytest -c packages/assets_gcs/pyproject.toml packages/assets_gcs/tests -q
python -m pytest -c workers/generation/pyproject.toml workers/generation/tests -q
python -m pytest -c apps/api/pyproject.toml apps/api/tests -q
python -m ruff check apps/api packages/auth packages/auth_oidc packages/parser packages/prompts packages/model_gateway packages/model_gateway_openai packages/assets packages/assets_gcs packages/persistence workers/generation
python -m ruff format --check apps/api packages/auth packages/auth_oidc packages/parser packages/prompts packages/model_gateway packages/model_gateway_openai packages/assets packages/assets_gcs packages/persistence workers/generation
```

Set `TEST_POSTGRES_URL` to run PostgreSQL-only concurrent revision CAS, generation claim,
generated-output asset uniqueness, and final-owner tests. SQLite tests are portable behavior tests
and are not presented as proof of PostgreSQL locking behavior.
