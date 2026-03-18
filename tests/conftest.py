"""Shared pytest fixtures."""

from __future__ import annotations

import logging

import pytest
import pytest_asyncio

from remora.core.storage.db import open_database


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


@pytest_asyncio.fixture
async def db(tmp_path):
    """Shared SQLite fixture configured with WAL mode."""
    database = await open_database(tmp_path / "test.db")
    yield database
    await database.close()
