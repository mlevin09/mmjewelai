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
python -m pip install -e './packages/model_gateway_google[test]'
python -m pip install -e './packages/model_gateway_openai[test]'
python -m pip install -e './packages/assets[test]'
python -m pip install -e './packages/assets_gcs[test]'
python -m pip install -e './packages/auth[test]'
python -m pip install -e './packages/auth_oidc[test]'
python -m pip install -e './packages/auth_identity_platform[test]'
python -m pip install -e './packages/persistence'
python -m pip install -e './workers/generation[test]'
python -m pip install -e './packages/parser[test]'
python -m pip install -e './packages/text_understanding_google[test]'
python -m pip install -e './apps/api[test]'
export DATABASE_URL='postgresql+psycopg://jewelai:jewelai@localhost:5432/jewelai'
export OIDC_ISSUER='https://identity.example/'
export OIDC_AUDIENCE='jewelai-api'
export OIDC_JWKS_URL='https://identity.example/.well-known/jwks.json'
export GCS_ASSET_BUCKET='jewelai-assets-prod'
# Optional upload limit in bytes; defaults to 20 MiB and cannot exceed 100 MiB:
export ASSET_UPLOAD_MAX_BYTES='20971520'
# Independent raw HTTP limit including multipart envelope headroom:
export HTTP_MAX_REQUEST_BYTES='22020096'
# Optional non-secret signing configuration:
export GCP_PROJECT_ID='jewelai-prod'
export GCS_SIGNING_SERVICE_ACCOUNT_EMAIL='signer@jewelai-prod.iam.gserviceaccount.com'
# Exact comma-separated browser origins. HTTP is accepted only for localhost development:
export WEB_ALLOWED_ORIGINS='http://localhost:5173'
# Optional Text Intake v1 provider. The key remains server-side:
export TEXT_UNDERSTANDING_PROVIDER='google'
export GOOGLE_TEXT_UNDERSTANDING_MODEL='gemini-3.1-flash-lite'
export GOOGLE_GENERATIVE_LANGUAGE_API_KEY='<runtime-secret>'
# Optional strict JSON array of non-secret server-side generation profiles:
export GENERATION_PROFILES_JSON='[{"profile_id":"default","profile_version":"1.0.0","provider":"openai","model":"gpt-image-1","configuration":{"output_count":1}}]'
alembic -c packages/persistence/alembic.ini upgrade head
uvicorn jewelai_api.app:create_app --factory
```

Production also configures `DB_POOL_SIZE`, `DB_MAX_OVERFLOW`, `DB_POOL_TIMEOUT_SECONDS`, and
`DB_POOL_RECYCLE_SECONDS`; these apply to non-SQLite engines only. Capacity must leave Cloud SQL
headroom beyond the combined maximum API, worker, and job pools for operators.

The raw ASGI limit rejects declared or streaming oversized bodies before multipart parsing and is
separate from the Asset policy limit. Middleware returns a server-generated `X-Request-ID`, safe
headers, and one JSON completion event with method, route template, status, and latency. It never
logs Authorization, query strings, request bodies, signed URLs, prompts, or image bytes.

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
- `GET /organizations/{organization_id}/projects`
- `POST /projects/{project_id}/sessions`
- `GET /projects/{project_id}/sessions`
- `GET /ui/catalog`
- `GET /sessions/{session_id}`
- `POST /sessions/{session_id}/messages`
- `POST /sessions/{session_id}/parser-proposals`
- `POST /sessions/{session_id}/text-intake`
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
- `POST /sessions/{session_id}/generation-runs/{generation_run_id}/retry`
- `POST|GET /sessions/{session_id}/visualization-iterations`
- `GET /sessions/{session_id}/visualization-iterations/{iteration_id}`
- `POST /sessions/{session_id}/visualization-iterations/{iteration_id}/decision`
- `POST /sessions/{session_id}/iterative-edits`
- `POST /sessions/{session_id}/iterative-edits/{edit_id}/messages`
- `GET /sessions/{session_id}/assets`
- `GET /sessions/{session_id}/dictionary-options`
- `POST /sessions/{session_id}/assets`
- `GET /sessions/{session_id}/assets/{asset_id}`
- `POST /sessions/{session_id}/assets/{asset_id}/access`

`GET /health` is public. Every product route requires a verified bearer JWT. The JWT establishes an
external identity, which resolves to a JewelAI principal; current database membership authorizes an
organization. Session routes use `X-Organization-ID` only as the requested tenant selector, never as
identity proof. Existing repository scopes remain defense in depth. Conversational roles never
grant permissions, and JWT role/group/organization claims are ignored.

`GET /ui/catalog` exposes only role IDs, supported locales, and safe generation profile summaries;
provider/model details and credentials are never returned. `GENERATION_PROFILES_JSON` is validated
as a strict, unique, bounded list at startup. Session dictionary options expose only active
localized canonical terms for the three v1 answer categories, using the session's pinned artifact
and locale. Project/session list order is deterministic and every list remains ownership-scoped.

CORS is disabled unless `WEB_ALLOWED_ORIGINS` is configured. Entries must be exact origins;
wildcards, userinfo, paths, query/fragment text, whitespace, and non-local HTTP origins fail startup.
The browser contract permits GET/POST/PATCH/DELETE/OPTIONS and Authorization, Content-Type, and
X-Organization-ID without credentialed CORS.

Production startup fails closed unless `OIDC_ISSUER`, `OIDC_AUDIENCE`, and HTTPS `OIDC_JWKS_URL` are
configured when `AUTH_PROVIDER=oidc` (the default, retained for production). Preproduction sets
`AUTH_PROVIDER=identity_platform` and `IDENTITY_PLATFORM_PROJECT_ID=mmjewellai-preprod`; it verifies
Firebase/Identity Platform ID tokens with Google's published signing keys and requires the exact
`securetoken.google.com/<project-id>` issuer and project-ID audience. Neither provider's email or
custom claims grant JewelAI organization access. The API also requires `GCS_ASSET_BUCKET` unless both an Asset access signer and object store
are explicitly injected;
`GCP_PROJECT_ID` and `GCS_SIGNING_SERVICE_ACCOUNT_EMAIL` are optional non-secret settings. Google
ADC/workload identity supplies credentials—service-account private-key JSON is not application
configuration. The resource server stores no token or raw claims. Existing pre-auth organizations are
not automatically claimed; any production backfill requires an explicit trusted process.

Runtime timestamps and IDs are server-owned. Transition message provenance is accepted from the
caller and checked by the existing domain model against the server revision timestamp. Evaluation
persists ASK lineage but never applies DERIVE/ASSUME proposals or mutates a revision.

Parser candidates are untrusted structured inputs. The API binds them to a persisted user message,
the session's resolved locale and pinned dictionary, then returns a deterministic proposal. The
manual parser-proposal endpoint remains non-mutating. Text Intake v1 first persists the original
message, calls one bounded server-side Google understanding adapter, validates the returned
`ParserCandidate`, and automatically applies only accepted proposal changes through the existing
EDIT/domain/CAS boundary. It then invokes the existing Rules Engine and Question Catalog. The model
cannot select questions, write revisions, confirm/lock fields, infer dimensions, compile prompts, or
start generation. Provider failures are typed and redacted.

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
does not recompile or compare against a newer current design revision. Provider adapters are never
constructed by `create_app()` and no API route invokes a provider. Production composition may inject
it into the worker with environment-managed credentials, bounded timeout, and disabled SDK retries.

Visualization iteration POST accepts one existing prompt revision and creates one independent
GenerationRun plus durable dispatch for every `iteration_enabled` runtime profile. All runs pin the
same prompt revision and content hash. Provider execution remains asynchronous and independent;
terminal mixed success is returned as `partial`, and successful READY Assets remain selectable.
Selection is organization/session/iteration scoped, persists one immutable contextual decision,
and derives Current Visual State without ranking providers or deleting rejected results.

Asset list/get endpoints expose scoped metadata only. They omit internal object keys, bytes, buckets,
and URLs. Authenticated `POST /sessions/{session_id}/assets` accepts one multipart field named
`file` and creates a reference Asset only. PNG, JPEG, and WebP declarations must match the existing
binary signature validation. The route reads fixed 64 KiB chunks, retaining at most the configured
limit plus one byte; the default is 20 MiB and the maximum configurable limit is 100 MiB. Session
scope supplies the project, the server supplies the UUID, and filename is neither trusted nor
persisted. Repeated successful POSTs create distinct Assets.

Production upload uses the same configured private GCS bucket and create-only object store as other
Asset flows. Storage errors are redacted. A crash after the durable write but before READY may leave
PENDING reference metadata; automated reference-PENDING reconciliation remains future work.

The explicit authenticated `POST .../assets/{asset_id}/access` action checks current database
membership and exact tenant/session/Asset scope, then uses the existing provider-neutral contract
and production GCS V4 signer to return a temporary HTTPS GET capability for a READY Asset. The
default TTL is five minutes and maximum is fifteen minutes. The JSON response is never redirected
or cached (`no-store, private`), and the URL is never persisted. Membership revocation blocks future
issuance but cannot revoke a capability already issued before its expiration. Upload never returns
a signed URL; clients request temporary read access separately. General reference retention remains
unimplemented.

## Verification

```sh
python -m pytest -c packages/parser/pyproject.toml packages/parser/tests -q
python -m pytest -c packages/text_understanding_google/pyproject.toml packages/text_understanding_google/tests -q
python -m pytest -c packages/auth/pyproject.toml packages/auth/tests -q
python -m pytest -c packages/auth_oidc/pyproject.toml packages/auth_oidc/tests -q
python -m pytest -c packages/prompts/pyproject.toml packages/prompts/tests -q
python -m pytest -c packages/model_gateway/pyproject.toml packages/model_gateway/tests -q
python -m pytest -c packages/model_gateway_google/pyproject.toml packages/model_gateway_google/tests -q
python -m pytest -c packages/model_gateway_openai/pyproject.toml packages/model_gateway_openai/tests -q
python -m pytest -c packages/assets/pyproject.toml packages/assets/tests -q
python -m pytest -c packages/assets_gcs/pyproject.toml packages/assets_gcs/tests -q
python -m pytest -c workers/generation/pyproject.toml workers/generation/tests -q
python -m pytest -c apps/api/pyproject.toml apps/api/tests -q
python -m ruff check apps/api packages/auth packages/auth_oidc packages/parser packages/prompts packages/model_gateway packages/model_gateway_google packages/model_gateway_openai packages/assets packages/assets_gcs packages/persistence workers/generation
python -m ruff format --check apps/api packages/auth packages/auth_oidc packages/parser packages/prompts packages/model_gateway packages/model_gateway_google packages/model_gateway_openai packages/assets packages/assets_gcs packages/persistence workers/generation
```

Set `TEST_POSTGRES_URL` to run PostgreSQL-only concurrent revision CAS, generation claim,
dispatch redrive, explicit retry, stale-recovery/worker completion, generated-output asset
uniqueness, principal creation, and final-owner tests. SQLite tests are portable behavior tests and
are not presented as proof of PostgreSQL locking behavior.

Generation creation atomically commits the PENDING GenerationRun and one dispatch-outbox row. The API
then attempts immediate Cloud Tasks publication but never executes a provider or GCS inline. Publication
failure leaves the accepted run PENDING and its outbox recoverable. Run a bounded redrive with
`python -m jewelai_api.dispatch_pending --batch-size 100`.

Production queue configuration uses `CLOUD_TASKS_PROJECT_ID`, `CLOUD_TASKS_LOCATION`,
`CLOUD_TASKS_QUEUE_ID`, `GENERATION_WORKER_TASK_URL`,
`GENERATION_TASK_SERVICE_ACCOUNT_EMAIL`, `GENERATION_TASK_OIDC_AUDIENCE`, and optional bounded
`CLOUD_TASKS_API_TIMEOUT_SECONDS`. Credentials come only from ADC/workload identity.

Generation retry accepts only strict `{}` and only for a FAILED run. It creates a new PENDING child
with a new UUID, exact historical prompt/profile/provider/model/configuration, incremented attempt,
and immediate-parent lineage. The child and outbox commit atomically; typed publication failure
leaves both recoverable. Repeating the same retry returns the existing direct child (201 when first
created, 200 thereafter). The original run is never reopened, no current profile is consulted, and
no prompt is recompiled or provider invoked inline.

Generated-Asset reconciliation and failed-run orphan cleanup are intentionally not HTTP routes.
They are bounded operator commands in `workers/generation`, with separate metadata-read and
version-conditional-delete authority. Existing Asset metadata and signed-access API contracts are
unchanged.
