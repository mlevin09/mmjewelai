# Observability

Dependency-free helpers shared by the API STT proxy, the generation worker and Asset ingestion.

`exception_diagnostics(exc)` returns only an exception's qualified type, its bounded cause chain
(including an implicit `__context__` hidden by `raise ... from None`) and the code locations
(`file:line:function`) where the innermost cause was raised. It never reads exception messages,
arguments, local variables or source lines, because those may carry provider payloads,
credentials or private user content. See [ADR 0048](../../docs/adr/0048-privacy-safe-failure-diagnostics.md).

Run tests with `python -m pytest -c packages/observability/pyproject.toml packages/observability/tests -q`.
