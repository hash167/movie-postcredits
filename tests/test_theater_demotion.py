"""Empty now_playing must not clear the theaters tier."""
import asyncio

from src.database import DatabaseManager


class _Conn:
    def __init__(self):
        self.queries = []

    async def execute(self, *args):
        self.queries.append(args)
        return "UPDATE 3"

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False


class _Pool:
    def __init__(self):
        self.conn = _Conn()

    def acquire(self):
        return self.conn


def test_empty_now_playing_skips_demotion():
    db = DatabaseManager.__new__(DatabaseManager)
    db.pool = _Pool()
    count = asyncio.run(db.demote_stale_theater_movies([]))
    assert count == 0
    assert db.pool.conn.queries == []


def test_now_playing_ids_limit_the_update():
    db = DatabaseManager.__new__(DatabaseManager)
    db.pool = _Pool()
    count = asyncio.run(db.demote_stale_theater_movies([11, 22]))
    assert count == 3
    sql, tier, _when, ids = db.pool.conn.queries[0]
    assert "NOT (id = ANY" in sql
    assert tier == "recent"
    assert ids == [11, 22]
