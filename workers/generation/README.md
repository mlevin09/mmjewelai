# Generation worker

Reserved for durable image-generation job processing.

Step 2 establishes only the repository location. Queue technology, persistence, provider calls, retries, idempotency, and deployment are intentionally deferred to later implementation work and ADRs.
The worker must consume validated, immutable specification revisions and must not redefine domain business rules.
