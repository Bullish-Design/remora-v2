"""Shared pytest fixtures."""

from __future__ import annotations

import asyncio
import sqlite3

import pytest


@pytest.fixture
def db_connection(tmp_path):
    """Shared SQLite connection with WAL mode."""
    db_path = tmp_path / "test.db"
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.row_factory = sqlite3.Row
    yield conn
    conn.close()


@pytest.fixture
def db_lock() -> asyncio.Lock:
    """Shared asyncio lock for SQLite serialization."""
    return asyncio.Lock()
