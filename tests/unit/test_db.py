from __future__ import annotations

from pathlib import Path

import pytest

from remora.core.db import AsyncDB


@pytest.mark.asyncio
async def test_asyncdb_execute_and_fetch(tmp_path: Path) -> None:
    db = AsyncDB.from_path(tmp_path / "db1.sqlite")
    await db.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, name TEXT)")
    await db.execute("INSERT INTO t(name) VALUES (?)", ("a",))
    row = await db.fetch_one("SELECT name FROM t WHERE id = 1")
    assert row is not None
    assert row["name"] == "a"
    db.close()


@pytest.mark.asyncio
async def test_asyncdb_fetch_all(tmp_path: Path) -> None:
    db = AsyncDB.from_path(tmp_path / "db2.sqlite")
    await db.execute_script(
        """
        CREATE TABLE t (id INTEGER PRIMARY KEY, value INTEGER);
        INSERT INTO t(value) VALUES (1);
        INSERT INTO t(value) VALUES (2);
        """
    )
    rows = await db.fetch_all("SELECT value FROM t ORDER BY value ASC")
    assert [row["value"] for row in rows] == [1, 2]
    db.close()


@pytest.mark.asyncio
async def test_asyncdb_insert_and_delete(tmp_path: Path) -> None:
    db = AsyncDB.from_path(tmp_path / "db3.sqlite")
    await db.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, name TEXT)")
    row_id = await db.insert("INSERT INTO t(name) VALUES (?)", ("x",))
    assert row_id == 1
    deleted = await db.delete("DELETE FROM t WHERE id = ?", (1,))
    assert deleted == 1
    db.close()


@pytest.mark.asyncio
async def test_asyncdb_execute_many(tmp_path: Path) -> None:
    db = AsyncDB.from_path(tmp_path / "db4.sqlite")
    await db.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, name TEXT)")
    await db.execute_many(
        [
            ("INSERT INTO t(name) VALUES (?)", ("a",)),
            ("INSERT INTO t(name) VALUES (?)", ("b",)),
        ]
    )
    rows = await db.fetch_all("SELECT name FROM t ORDER BY id ASC")
    assert [row["name"] for row in rows] == ["a", "b"]
    db.close()
