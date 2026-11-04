"""Shared F05 matrix fixtures; exhaustive SQLite journeys are collected last.

Keep the existing disposable-PG freshness gate intact: slow non-DDL language
journeys must not age the CI container before the PostgreSQL fixtures run.
"""

from test_z_f05_matrix import TEXT, current_offer, source_setup

__all__ = ["TEXT", "current_offer", "source_setup"]
