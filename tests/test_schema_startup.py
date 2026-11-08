"""Disposable local Postgres only. Never uses a production DSN."""
import asyncio
import os

import pytest

pytest.importorskip("asyncpg")

TEST_DSN = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql://moviesync:test-only-db@127.0.0.1:5432/moviesync",
)


def _local_only(dsn: str) -> bool:
    return "127.0.0.1" in dsn or "localhost" in dsn


BASE_SQL = """
CREATE TABLE IF NOT EXISTS movies (
    id INTEGER PRIMARY KEY,
    title VARCHAR(500) NOT NULL,
    year INTEGER,
    release_date VARCHAR(50),
    runtime_minutes INTEGER DEFAULT 0,
    poster_path TEXT,
    overview TEXT,
    vote_average DECIMAL(3, 1),
    popularity DECIMAL(10, 3),
    tier VARCHAR(50),
    imdb_id VARCHAR(20),
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS post_credits (
    id SERIAL PRIMARY KEY,
    movie_id INTEGER REFERENCES movies(id) ON DELETE CASCADE UNIQUE,
    has_scene BOOLEAN DEFAULT FALSE,
    scene_count INTEGER DEFAULT 0,
    mid_credits TEXT,
    post_credits TEXT,
    worth_staying BOOLEAN,
    spoiler_free_hint TEXT,
    source_confidence VARCHAR(50) DEFAULT 'medium'
);
CREATE TABLE IF NOT EXISTS easter_eggs (
    id SERIAL PRIMARY KEY,
    movie_id INTEGER REFERENCES movies(id) ON DELETE CASCADE,
    description TEXT,
    title TEXT,
    significance VARCHAR(20)
);
"""


async def _reset(conn):
    await conn.execute("DROP VIEW IF EXISTS movies_complete")
    await conn.execute("DROP TABLE IF EXISTS movie_insights CASCADE")
    await conn.execute("DROP TABLE IF EXISTS extract_jobs CASCADE")
    await conn.execute("DROP TABLE IF EXISTS batch_logs CASCADE")
    await conn.execute("DROP TABLE IF EXISTS easter_eggs CASCADE")
    await conn.execute("DROP TABLE IF EXISTS post_credits CASCADE")
    await conn.execute("DROP TABLE IF EXISTS movies CASCADE")
    await conn.execute(BASE_SQL)


def test_ensure_schema_startup_and_concurrent_pods():
    if not _local_only(TEST_DSN):
        pytest.skip("refusing non-local database")
    import asyncpg
    from src.database import DatabaseManager

    async def once():
        conn = await asyncpg.connect(TEST_DSN)
        try:
            await _reset(conn)
        finally:
            await conn.close()
        from src import config
        config.settings.database_url = TEST_DSN
        managers = [DatabaseManager(), DatabaseManager()]
        await asyncio.gather(*(m.connect() for m in managers))
        try:
            check = await asyncpg.connect(TEST_DSN)
            try:
                kind = await check.fetchval(
                    "SELECT relkind FROM pg_class WHERE relname = 'movies_complete'"
                )
                sig = await check.fetchval(
                    """
                    SELECT data_type FROM information_schema.columns
                    WHERE table_name = 'easter_eggs' AND column_name = 'significance'
                    """
                )
                await check.execute(
                    "INSERT INTO movies (id, title) VALUES (1, 'Example') ON CONFLICT DO NOTHING"
                )
                row = await check.fetchrow("SELECT id, title FROM movies_complete WHERE id = 1")
            finally:
                await check.close()
        finally:
            await asyncio.gather(*(m.close() for m in managers))
        assert kind in ("v", b"v")
        assert sig == "text"
        assert row["title"] == "Example"

    asyncio.run(once())
