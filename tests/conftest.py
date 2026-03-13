"""Shared pytest fixtures."""

from __future__ import annotations

import logging

import pytest

from remora.core.db import AsyncDB


def _remove_closed_root_stream_handlers() -> None:
    root_logger = logging.getLogger()
    for handler in list(root_logger.handlers):
        stream = getattr(handler, "stream", None)
        if stream is None or not getattr(stream, "closed", False):
            continue
        root_logger.removeHandler(handler)
        handler.close()


@pytest.fixture(autouse=True)
def cleanup_closed_root_stream_handlers():
    _remove_closed_root_stream_handlers()
    yield
    _remove_closed_root_stream_handlers()


@pytest.fixture
def db(tmp_path):
    """Shared AsyncDB fixture configured with WAL mode."""
    database = AsyncDB.from_path(tmp_path / "test.db")
    yield database
    database.close()
