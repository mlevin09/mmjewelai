# Contract fixtures

valid/ contains four complete snapshots: initial ring, empty intake, derived dimensions, and
disclosed assumption with an inapplicable construction field.
invalid/ contains isolated structural violations rejected by both JSON Schema and Python validation.

Every asset ID, message, policy and KB record is synthetic. The 8 x 6 x 4 mm dimensions exist only
to test serialization. They are not verified gemstone measurements or a weight-to-size table.
No production domain catalog or approved default is provided here.

Python-only semantic failures (duplicate stable group IDs, self-parent IDs, timestamp ordering)
and history-dependent lock/stale-revision behavior are tested in packages/domain/tests.
