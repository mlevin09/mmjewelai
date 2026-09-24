# JewelAI parser package

This provider-neutral package validates untrusted `ParserCandidate` values and builds deterministic,
schema-safe `ParserProposal` results. It depends only on Pydantic and `packages/domain`; it has no
FastAPI, persistence, provider SDK, prompt, network, clock, UUID generation, or Rules Engine call.

See the [Parser Proposal v1 specification](../../specs/parser/README.md). Install and test from the
repository root:

```sh
python -m pip install -e './packages/domain[test]'
python -m pip install -e './packages/parser[test]'
python -m pytest -c packages/parser/pyproject.toml packages/parser/tests -q
```
