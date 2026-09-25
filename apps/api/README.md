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
python -m pip install -e './packages/persistence'
python -m pip install -e './workers/generation[test]'
python -m pip install -e './packages/parser[test]'
python -m pip install -e './apps/api[test]'
export DATABASE_URL='postgresql+psycopg://jewelai:jewelai@localhost:5432/jewelai'
alembic -c packages/persistence/alembic.ini upgrade head
uvicorn jewelai_api.app:create_app --factory
```

`DATABASE_URL` and explicit artifact versions configure the runtime. Sessions persist their schema,
role, dictionary, question, rules, and prompt-template versions at creation; they never follow a
“latest” file.

## API scope

- `GET /health`
- `POST /organizations`
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

Session routes use `X-Organization-ID` as an explicit ownership scope. This is plumbing for future
authenticated context, **not authentication** and not a security claim. Conversational roles never
grant permissions.

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

Asset endpoints expose scoped metadata only. They omit internal object keys, bytes, buckets, and
URLs. Asset ingestion and signed-read contracts are internal reusable boundaries in `packages/assets`;
the production GCS adapter is isolated in `packages/assets_gcs`. This API exposes no binary
upload/download, registers no object store or signer, and has no route that issues signed URLs.
Authentication, authenticated asset access, retention, and reconciliation remain unimplemented.

## Verification

```sh
python -m pytest -c packages/parser/pyproject.toml packages/parser/tests -q
python -m pytest -c packages/prompts/pyproject.toml packages/prompts/tests -q
python -m pytest -c packages/model_gateway/pyproject.toml packages/model_gateway/tests -q
python -m pytest -c packages/model_gateway_openai/pyproject.toml packages/model_gateway_openai/tests -q
python -m pytest -c packages/assets/pyproject.toml packages/assets/tests -q
python -m pytest -c packages/assets_gcs/pyproject.toml packages/assets_gcs/tests -q
python -m pytest -c workers/generation/pyproject.toml workers/generation/tests -q
python -m pytest -c apps/api/pyproject.toml apps/api/tests -q
python -m ruff check apps/api packages/parser packages/prompts packages/model_gateway packages/model_gateway_openai packages/assets packages/assets_gcs packages/persistence workers/generation
python -m ruff format --check apps/api packages/parser packages/prompts packages/model_gateway packages/model_gateway_openai packages/assets packages/assets_gcs packages/persistence workers/generation
```

Set `TEST_POSTGRES_URL` to run PostgreSQL-only concurrent revision CAS, generation claim, and
generated-output asset uniqueness tests. SQLite tests are portable behavior tests and are not
presented as proof of PostgreSQL locking behavior.
