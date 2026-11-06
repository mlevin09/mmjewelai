"""Reuse the existing fresh disposable CI cluster/schema gate; never spoof it locally."""

import pytest
from test_generation_preparations_postgres import engine as engine
from test_session_retirement import (
    test_retirement_blocks_active_generation_and_preserves_outbox as _active,
)
from test_session_retirement import (
    test_retirement_waits_for_successful_run_asset_finalization as _materialization,
)

pytestmark = pytest.mark.postgres


def test_retirement_active_generation_postgres(client, app, engine):
    _active(client, app, running=True)


def test_retirement_asset_retention_postgres(client, app, engine):
    _materialization(client, app, engine)
