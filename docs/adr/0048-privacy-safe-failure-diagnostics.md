# ADR 0048 — Privacy-safe failure diagnostics

Status: Owner-requested on 21.11.2026 (code-review finding 1: silently swallowed exceptions);
implementation for independent review in a Draft PR. Not acceptance, release or deployment.

## Context

Handled failures in the generation worker (`service.py`), Asset ingestion (`ingestion.py`) and
the API STT proxy (`app.py`) were mapped to sanitized codes such as `gateway_unavailable`,
`materialization_failed` or `stt_unavailable` and returned without any log record. Provider
adapters raise `... from None`, which
hides the real cause from tracebacks. Production failures therefore could not be diagnosed.

The existing loggers deliberately never serialize exception messages or provider payloads,
because those can carry prompts, signed URLs, credentials or private user content. That rule
stays.

## Decision

1. Add `packages/observability` (`jewelai-observability`), a dependency-free leaf package with one
   function, `exception_diagnostics(exc)`. It returns only:
   - `error_type`: the qualified exception type;
   - `error_chain`: at most 5 qualified types along `__cause__`, else `__context__` — the
     implicit context is followed even under `from None`; cycles are bounded;
   - `error_origin`: at most 8 innermost `file:line:function` frames of the deepest cause.
   It never reads messages, arguments, local variables or source lines.
2. Every handled failure path above emits one structured event with those fields at ERROR
   (an Asset storage conflict at WARNING), next to the existing identifiers
   (`generation_run_id`, `asset_id`, `organization_id`, `session_id`). External responses and
   persisted error codes/details are unchanged.
3. Asset ingestion logs to `jewelai.assets`; the API runtime attaches its JSON handler to it.
4. `jewelai-assets`, `jewelai-generation-worker` and `jewelai-api` declare the dependency; the API
   and worker images, `install_runtime.sh`, Full Regression lint scope and `pr_routes.json`
   ownership (component `observability`) include the package.

## Alternatives

- Log `exc_info` / full tracebacks: rejected; messages and source lines can carry private data.
- Keep a private copy of the helper in each runtime: rejected after review; two copies of a
  privacy rule drift. Placing it in an existing package (`jewelai_assets`, `jewelai_model_gateway`)
  would give that package an unrelated responsibility.
- Carry diagnostics only in the worker HTTP response or in persisted run details: rejected; both
  are stored or exposed, while logs are the operational channel.

## Consequences

- Failures behind sanitized codes are diagnosable from logs by type and code location. The first
  run already showed that an existing worker test reached an executor lookup `KeyError`, not the
  provider failure its name suggests.
- One new event per handled failure; no new event on success.
- Changes to `apps/api/src/jewelai_api/app.py` fall under its reviewed `source_pair` contract
  in `tools/ci/pr_routes.json`; this PR does not update that pair. The independent coordinator
  reviews and pins it.
- Follow-up, not in this change: `RequestObservabilityMiddleware` still logs an unhandled API
  error by its bare class name. `middleware.py` has no ownership mapping in `pr_routes.json`,
  so adding the same diagnostics there needs that ownership decision first.
