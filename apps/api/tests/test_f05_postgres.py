"""F05 read paths on the existing independently identified disposable PG service.

This proves the implemented preview/projection subset, not the unfinished F05
writer transaction/rollback/concurrency requirements.
"""

import pytest
from test_f05_compatibility import (
    test_required_unknown_is_discharged_only_by_actual_same_target_correction as _unknown,
)
from test_f05_preview import (
    test_negotiated_output_roundtrip_restart_no_writes_and_no_preparation as _read_only,
)
from test_f05_preview import (
    test_orphan_message_does_not_stale_but_correction_does as _stale,
)
from test_generation_preparations_postgres import engine as engine

pytestmark = pytest.mark.postgres


@pytest.mark.parametrize("base", ["L", "F"])
@pytest.mark.parametrize("locale", ["en", "ru"])
def test_f05_read_projection_postgres(engine, tmp_path, base, locale):
    _read_only(engine, tmp_path, base, locale)


def test_f05_unknown_causal_projection_postgres(engine, tmp_path):
    _unknown(engine, tmp_path)


def test_f05_read_frame_cas_postgres(engine, tmp_path):
    _stale(engine, tmp_path)
