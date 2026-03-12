"""Shared pytest fixtures."""

from __future__ import annotations

import pytest

from remora.core.db import AsyncDB


@pytest.fixture
def db(tmp_path):
    """Shared AsyncDB fixture configured with WAL mode."""
    database = AsyncDB.from_path(tmp_path / "test.db")
    yield database
    database.close()
