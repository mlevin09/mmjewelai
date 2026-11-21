"""Storage failures during ingestion are recorded by exception identity, never by message."""

import logging

import pytest
from test_assets import PNG, MemoryObjectStore, MemoryRepository, request, ticking_clock

from jewelai_assets import (
    AssetErrorCode,
    AssetStatus,
    AssetStorageConflictError,
    AssetStorageError,
    ingest_asset,
)

LEAK = "controlled test failure"


class UnexpectedStoreError(RuntimeError):
    pass


def _ingest(failure):
    return ingest_asset(
        request=request(),
        content=PNG,
        repository=MemoryRepository(),
        object_store=MemoryObjectStore(failure=failure),
        clock=ticking_clock(),
    )


def _records(caplog):
    return [r for r in caplog.records if r.name == "jewelai.assets"]


@pytest.mark.parametrize(
    "failure,event,level,code",
    [
        (AssetStorageError, "asset_storage_unavailable", logging.ERROR, "storage_unavailable"),
        (
            UnexpectedStoreError,
            "asset_storage_unexpected_error",
            logging.ERROR,
            "storage_unavailable",
        ),
        (AssetStorageConflictError, "asset_storage_conflict", logging.WARNING, "storage_conflict"),
    ],
)
def test_storage_failures_are_logged_with_identity_only(caplog, failure, event, level, code):
    caplog.set_level(logging.INFO, logger="jewelai.assets")
    asset = _ingest(failure)

    assert asset.status is AssetStatus.FAILED
    assert asset.error_code is AssetErrorCode(code)
    [record] = _records(caplog)
    fields = record.jewelai_fields
    assert record.levelno == level
    assert fields["event"] == event
    assert fields["asset_id"] == str(asset.asset_id)
    assert fields["organization_id"] == str(asset.organization_id)
    assert fields["error_type"].endswith("." + failure.__qualname__)
    assert fields["error_origin"][-1].endswith(":put_if_absent")
    assert LEAK not in record.getMessage()
    assert LEAK not in repr(fields)
    assert asset.object_key not in repr(fields)


def test_successful_ingestion_logs_nothing(caplog):
    caplog.set_level(logging.INFO, logger="jewelai.assets")
    assert _ingest(None).status is AssetStatus.READY
    assert _records(caplog) == []
