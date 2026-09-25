# Repository-level tests

Reserved for cross-package integration, contract, and acceptance tests that span multiple JewelAI V2 components.

Package-local unit tests stay with their package; for example, the Jewelry Design Schema tests remain
under `packages/domain/tests`. `test_openai_generation_pipeline.py` is intentionally repository-level:
it proves the no-network cross-package path from a persisted prompt through the real OpenAI adapter
translation and worker boundary to a READY generated Asset and fake private object store.

```sh
python -m pytest -c workers/generation/pyproject.toml tests/test_openai_generation_pipeline.py -q
```
