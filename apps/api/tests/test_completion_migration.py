"""Portable metadata check of only the new additive migration; no shared database."""

import importlib.util
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect


def test_completion_routes_absent_by_default(client):
    assert not any("/completions" in route.path for route in client.app.routes)


def test_completion_additive_migration_matches_model():
    root = Path(__file__).resolve().parents[3]
    spec = importlib.util.spec_from_file_location(
        "completion_migration",
        root / "packages/persistence/migrations/versions/0019_prompt_completion.py",
    )
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = create_engine("sqlite://")
    with engine.begin() as db:
        with Operations.context(MigrationContext.configure(db)):
            migration.upgrade()
        inspector = inspect(db)
        from jewelai_persistence.models import PromptCompletionRow

        assert {c["name"] for c in inspector.get_columns("prompt_completion")} == set(
            PromptCompletionRow.__table__.columns.keys()
        )
        assert {
            tuple(x["column_names"]) for x in inspector.get_unique_constraints("prompt_completion")
        } == {("session_id", "request_id"), ("session_id", "sequence_number")}
    engine.dispose()


def test_completion_activation_requires_exact_reviewed_policy(tmp_path, monkeypatch):
    import pytest
    from jewelai_prompts.completion import CompletionRegistry

    from jewelai_api.completion import load_registry
    from jewelai_api.settings import RuntimeSettings, _completion_policy_path

    policy = CompletionRegistry(
        registry_id="test_only", version="1.0.0", review_status="APPROVED", rules=(), eligibility=()
    )
    path = tmp_path / "policy.json"
    path.write_text(policy.model_dump_json())
    assert load_registry(path, policy.sha256) == policy
    with pytest.raises(ValueError, match="binding mismatch"):
        load_registry(path, "0" * 64)
    path.write_text(policy.model_copy(update={"review_status": "PROPOSED"}).model_dump_json())
    with pytest.raises(ValueError, match="approval"):
        load_registry(path, policy.sha256)
    with pytest.raises(ValueError, match="SHA-256"):
        RuntimeSettings(completion_policy_path=path)
    monkeypatch.setenv("PROMPT_COMPLETION_ENABLED", "false")
    assert _completion_policy_path() is None
    monkeypatch.setenv("PROMPT_COMPLETION_ENABLED", "maybe")
    with pytest.raises(ValueError):
        _completion_policy_path()


@pytest.mark.parametrize(
    "code,expected", [("40001", "conflict"), ("23505", "conflict"), ("42P01", "unavailable")]
)
def test_completion_storage_failures_are_bounded(monkeypatch, code, expected):
    from contextlib import nullcontext
    from types import SimpleNamespace

    import jewelai_persistence.completion as storage
    from sqlalchemy.exc import OperationalError

    class DBError(Exception):
        pass

    original = DBError("TEST ONLY")
    original.sqlstate = code

    def fail(*args):
        raise OperationalError("TEST ONLY", None, original)

    monkeypatch.setattr(storage, "_authorize_and_lock", fail)
    repository = SimpleNamespace(_session_factory=SimpleNamespace(begin=lambda: nullcontext(None)))
    failure = (
        storage.CompletionStorageConflict
        if expected == "conflict"
        else storage.CompletionStorageUnavailable
    )
    with pytest.raises(failure):
        storage.completion_transaction(repository, None, None, None, lambda *args: None)
