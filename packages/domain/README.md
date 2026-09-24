# JewelAI domain package

Issue #1 implements an offline, immutable Jewelry Design Schema and revision transitions. Issue #2
adds versioned conversational Role Profiles, and Issue #3 adds deterministic Domain Dictionary
normalization. Neither policy artifact alters the schema transitions.
Python 3.12+ is required. This package is independent of the legacy root packaging.

From the repository root, inside your Python environment:

```sh
python -m pip install -e './packages/domain[test]'
python -m pytest -c packages/domain/pyproject.toml packages/domain/tests -q
python -m ruff check packages/domain
python -m ruff format --check packages/domain
```

The root V1 package references a missing app/ directory; install this package by its explicit path.
For runtime consumers, omit the test extra. The only runtime dependency is Pydantic, already selected
in the repository's Python stack. It provides typed validation, immutable models and schema export.
The test-only jsonschema dependency independently checks the published wire contract; pytest and
Ruff provide tests and static checks. No API, database or provider dependencies are imported.

See the [contract](../../specs/jewelry-design-schema/README.md) and
[fixtures](../../specs/jewelry-design-schema/fixtures/README.md), plus the
[Role Profiles contract](../../specs/roles/README.md) and
[Domain Dictionary contract](../../specs/dictionary/README.md).

```python
from pathlib import Path
from jewelai_domain import DesignRevision, unlock_field
from jewelai_domain.models import MessageSource
from datetime import datetime, timezone

revision = DesignRevision.model_validate_json(
    Path("specs/jewelry-design-schema/fixtures/valid/ring.json").read_text()
)
now = datetime.now(timezone.utc)
next_revision = unlock_field(
    revision,
    "metal.color",
    expected_revision_id=revision.revision_id,
    source=MessageSource(message_id="user-unlock-message", recorded_at=now),
    reason="User requested a different metal color",
    created_at=now,
)
assert revision.design.metal.color.locked
assert not next_revision.design.metal.color.locked
```

Use revise_design to apply an unconfirmed proposal, confirm_field to reconfirm the accepted value,
then lock_field if needed. A lock is not an authorization permission. Future services must authenticate
the actor and load the latest stored revision before calling these functions.

Re-export the schema from the repository root:

```sh
python -m jewelai_domain.schema specs/jewelry-design-schema/schema.json
python -m jewelai_domain.roles_schema specs/roles/schema.json
python -m jewelai_domain.dictionary_schema specs/dictionary/schema.json
```

The committed schema must match the exporter; tests detect drift. Regenerate and review the diff
when upgrading Pydantic. This version was validated with Pydantic 2.13.5.
