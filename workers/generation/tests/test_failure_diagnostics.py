"""Handled worker failures are logged by exception identity, never by message."""

import io
import json
import logging

from jewelai_model_gateway import GatewayUnavailableError
from test_generation_worker import (
    ORG_ID,
    RUN_ID,
    SESSION_ID,
    FakeExecutor,
    MemoryObjectStore,
    advancing_clock,
    persisted,
)

from jewelai_generation import ExecutorRegistry, execute_generation_run_with_assets
from jewelai_generation.logging import JsonLogFormatter

__all__ = ["persisted"]  # Shared fixture re-used from the native worker suite.

SECRET_DETAIL = "sk-live-secret customer prompt 10.0.0.5"


class RaisingExecutor(FakeExecutor):
    def __init__(self, error_factory):
        super().__init__()
        self.error_factory = error_factory

    def execute(self, request, *, edit_input=None):
        self.calls += 1
        raise self.error_factory()


def _sanitized_unavailable():
    try:
        {}["upstream-" + SECRET_DETAIL]
    except KeyError:
        raise GatewayUnavailableError from None


class _CapturedWorkerLog:
    def __enter__(self):
        self.stream = io.StringIO()
        self.handler = logging.StreamHandler(self.stream)
        self.handler.setFormatter(JsonLogFormatter())
        self.logger = logging.getLogger("jewelai.generation")
        self.previous_level = self.logger.level
        self.logger.setLevel(logging.INFO)
        self.logger.addHandler(self.handler)
        return self

    def __exit__(self, *exc_info):
        self.logger.removeHandler(self.handler)
        self.logger.setLevel(self.previous_level)

    def events(self):
        return [json.loads(line) for line in self.stream.getvalue().splitlines()]

    def raw(self):
        return self.stream.getvalue()


def _execute_with(repository, executor, store=None):
    return execute_generation_run_with_assets(
        repository,
        session_id=SESSION_ID,
        generation_run_id=RUN_ID,
        organization_id=ORG_ID,
        executors=ExecutorRegistry({"test": executor}),
        object_store=store or MemoryObjectStore(),
        clock=advancing_clock(),
    )


def test_unexpected_executor_error_is_logged_by_type_and_location_only(persisted):
    repository, _, _ = persisted
    with _CapturedWorkerLog() as log:
        outcome = _execute_with(repository, RaisingExecutor(lambda: RuntimeError(SECRET_DETAIL)))

    assert outcome.disposition == "failed"
    assert outcome.run.error_code.value == "gateway_unavailable"
    [event] = [e for e in log.events() if e["event"] == "generation_unexpected_error"]
    assert event["severity"] == "ERROR"
    assert event["generation_run_id"] == str(RUN_ID)
    assert event["error_type"] == "builtins.RuntimeError"
    assert event["error_chain"] == ["builtins.RuntimeError"]
    assert event["error_origin"][-1].startswith("test_failure_diagnostics.py:")
    assert event["error_origin"][-1].endswith(":execute")
    assert "sk-live" not in log.raw()
    assert "customer prompt" not in log.raw()


def test_sanitized_gateway_error_reveals_suppressed_cause_type_not_message(persisted):
    repository, _, _ = persisted
    with _CapturedWorkerLog() as log:
        outcome = _execute_with(repository, RaisingExecutor(_sanitized_unavailable))

    assert outcome.disposition == "failed"
    [event] = [e for e in log.events() if e["event"] == "generation_gateway_error"]
    assert event["error_chain"] == [
        "jewelai_model_gateway.gateway.GatewayUnavailableError",
        "builtins.KeyError",
    ]
    assert event["error_origin"][-1].endswith(":_sanitized_unavailable")
    assert "upstream-" not in log.raw()
    assert "sk-live" not in log.raw()


def test_pre_success_staging_failure_is_logged(persisted):
    repository, _, _ = persisted
    store = MemoryObjectStore(fail=True)
    with _CapturedWorkerLog() as log:
        outcome = _execute_with(repository, FakeExecutor(), store)

    assert outcome.disposition == "failed"
    [event] = [e for e in log.events() if e["event"] == "generation_output_staging_failed"]
    assert event["error_type"] == "jewelai_assets.storage.AssetStorageError"
    assert "secret storage failure" not in log.raw()


def test_post_success_materialization_failure_is_logged_without_message(persisted):
    repository, _, _ = persisted
    original_create = repository.create_pending_asset

    def fail_metadata(_asset):
        raise RuntimeError(SECRET_DETAIL)

    repository.create_pending_asset = fail_metadata
    try:
        with _CapturedWorkerLog() as log:
            outcome = _execute_with(repository, FakeExecutor())
    finally:
        repository.create_pending_asset = original_create

    assert outcome.disposition == "materialization_failed"
    [event] = [e for e in log.events() if e["event"] == "generation_asset_materialization_failed"]
    assert event["generation_run_id"] == str(RUN_ID)
    assert event["error_chain"] == ["builtins.RuntimeError"]
    assert event["error_origin"][-1].endswith(":fail_metadata")
    assert "sk-live" not in log.raw()


def test_successful_run_logs_no_failure_events(persisted):
    repository, _, _ = persisted
    with _CapturedWorkerLog() as log:
        outcome = _execute_with(repository, FakeExecutor())

    assert outcome.disposition == "succeeded"
    assert log.events() == []
