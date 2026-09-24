# JewelAI V2 API

This FastAPI application is the first runtime boundary around the deterministic domain package. HTTP
routes call application services; services call `jewelai_domain` transitions and the SQLAlchemy
repository. The domain package imports neither FastAPI nor SQLAlchemy.

## Local setup

Python 3.12+ and PostgreSQL are the production-compatible target:

```sh
python -m pip install -e './packages/domain[test]'
python -m pip install -e './packages/prompts[test]'
python -m pip install -e './packages/persistence'
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

## Verification

```sh
python -m pytest -c packages/parser/pyproject.toml packages/parser/tests -q
python -m pytest -c packages/prompts/pyproject.toml packages/prompts/tests -q
python -m pytest -c apps/api/pyproject.toml apps/api/tests -q
python -m ruff check apps/api packages/parser packages/prompts packages/persistence
python -m ruff format --check apps/api packages/parser packages/prompts packages/persistence
```

Set `TEST_POSTGRES_URL` to run the PostgreSQL-only concurrent CAS test. SQLite tests are portable
behavior tests and are not presented as proof of PostgreSQL locking behavior.
