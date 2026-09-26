# Generation Queue

Provider-neutral, immutable Generation Task v1 contracts and bounded transactional-outbox redrive.
The task contains only schema, run, session, and organization identifiers. It never contains prompts,
credentials, user tokens, object keys, URLs, base64, or binary data.

Run tests with `python -m pytest -c packages/generation_queue/pyproject.toml packages/generation_queue/tests -q`.
