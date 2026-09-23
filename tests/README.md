# Repository-level tests

Reserved for cross-package integration, contract, and acceptance tests that span multiple JewelAI V2 components.

Package-local unit tests stay with their package; for example, the existing Jewelry Design Schema tests remain under `packages/domain/tests`.
Step 2 adds no new runtime behavior, so it does not move or duplicate the existing domain test suite.
