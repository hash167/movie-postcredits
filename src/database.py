import asyncpg
from typing import List, Dict, Optional
from datetime import datetime
from src.config import settings
from src.models import EnhancedMovie


class DatabaseManager:
    def __init__(self):
        self.pool = None

    async def connect(self):
        self.pool = await asyncpg.create_pool(
            dsn=settings.database_url,
            min_size=2,
            max_size=10,
        )
        await self.ensure_schema()

    async def ensure_schema(self):
        """Create tables the image expects if a fresh/partial DB is missing them."""
        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS batch_logs (
                    id SERIAL PRIMARY KEY,
                    tier VARCHAR(50),
                    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    completed_at TIMESTAMP,
                    movies_processed INTEGER DEFAULT 0,
                    movies_failed INTEGER DEFAULT 0,
                    status VARCHAR(50) DEFAULT 'running'
                )
                """
            )
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS extract_jobs (
                    id SERIAL PRIMARY KEY,
                    movie_id INT NOT NULL UNIQUE,
                    title TEXT,
                    year INT,
                    status VARCHAR(20) NOT NULL DEFAULT 'queued',
                    attempts INT DEFAULT 0,
                    last_error TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    started_at TIMESTAMP,
                    finished_at TIMESTAMP,
                    locked_at TIMESTAMP
                )
                """
            )
            await conn.execute(
                """
                CREATE INDEX IF NOT EXISTS extract_jobs_status_created_idx
                ON extract_jobs (status, created_at)
                """
            )
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS movie_insights (
                    id SERIAL PRIMARY KEY,
                    movie_id INTEGER NOT NULL UNIQUE REFERENCES movies(id) ON DELETE CASCADE,
                    discussion_count INTEGER DEFAULT 0,
                    scraped_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            await conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_movie_insights_movie_id
                ON movie_insights (movie_id)
                """
            )
            async with conn.transaction():
                await conn.execute("SELECT pg_advisory_xact_lock(872314)")
                await conn.execute("DROP VIEW IF EXISTS movies_complete")
                await conn.execute(
                    "ALTER TABLE easter_eggs ALTER COLUMN significance TYPE TEXT"
                )
                await conn.execute(
                    "ALTER TABLE easter_eggs ADD COLUMN IF NOT EXISTS source_url TEXT"
                )
                await conn.execute(
                    "ALTER TABLE movie_insights "
                    "ADD COLUMN IF NOT EXISTS source_urls TEXT[]"
                )
                await conn.execute(
                """
                CREATE VIEW movies_complete AS
                SELECT m.id,
                    m.title,
                    m.year,
                    m.release_date,
                    m.runtime_minutes,
                    m.poster_path,
                    m.overview,
                    m.vote_average,
                    m.popularity,
                    m.tier,
                    m.imdb_id,
                    m.updated_at,
                    pc.has_scene,
                    pc.scene_count,
                    pc.mid_credits,
                    pc.post_credits AS post_credits_desc,
                    pc.worth_staying,
                    pc.spoiler_free_hint,
                    pc.source_confidence,
                    ri.discussion_count,
                    ri.scraped_at AS reddit_scraped_at,
                    ri.source_urls,
                    ( SELECT json_agg(json_build_object(
                          'detail', COALESCE(ee.description, ee.title::text),
                          'significance', ee.significance,
                          'source_url', ee.source_url)) AS json_agg
                       FROM easter_eggs ee
                      WHERE ee.movie_id = m.id) AS easter_eggs
                FROM movies m
                LEFT JOIN post_credits pc ON m.id = pc.movie_id
                LEFT JOIN movie_insights ri ON m.id = ri.movie_id
                """
            )

    async def close(self):
        if self.pool:
            await self.pool.close()

    async def upsert_movie(self, movie: EnhancedMovie):
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute(
                    """
                    INSERT INTO movies (
                        id, title, year, release_date, runtime_minutes,
                        poster_path, overview, vote_average, popularity,
                        tier, imdb_id, updated_at
                    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9,
                              $10, $11, $12)
                    ON CONFLICT (id) DO UPDATE SET
                        title=EXCLUDED.title,
                        poster_path=EXCLUDED.poster_path,
                        overview=EXCLUDED.overview,
                        vote_average=EXCLUDED.vote_average,
                        popularity=EXCLUDED.popularity,
                        tier=EXCLUDED.tier,
                        updated_at=EXCLUDED.updated_at
                    """,
                    movie.id,
                    movie.title,
                    movie.year,
                    movie.release_date,
                    movie.runtime_minutes,
                    movie.poster_path,
                    movie.overview,
                    movie.vote_average,
                    movie.popularity,
                    movie.tier,
                    movie.imdb_id,
                    datetime.now(),
                )
                if movie.movie_insights:
                    pc = movie.movie_insights.post_credits
                    mid_cred = (
                        pc.descriptions[0] if len(pc.descriptions) > 0
                        else None
                    )
                    post_cred = (
                        pc.descriptions[1] if len(pc.descriptions) > 1
                        else None
                    )
                    await conn.execute(
                        """
                        INSERT INTO post_credits (
                            movie_id, has_scene, scene_count, mid_credits,
                            post_credits, worth_staying, spoiler_free_hint,
                            source_confidence
                        ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                        ON CONFLICT (movie_id) DO UPDATE SET
                            has_scene=EXCLUDED.has_scene,
                            scene_count=EXCLUDED.scene_count,
                            mid_credits=EXCLUDED.mid_credits,
                            post_credits=EXCLUDED.post_credits,
                            worth_staying=EXCLUDED.worth_staying,
                            spoiler_free_hint=EXCLUDED.spoiler_free_hint,
                            source_confidence=EXCLUDED.source_confidence
                        """,
                        movie.id,
                        pc.has_scene,
                        pc.scene_count,
                        mid_cred,
                        post_cred,
                        None if pc.worth_staying is None else ("yes" if pc.worth_staying else "no"),
                        pc.spoiler_free_hint,
                        "medium",
                    )
                    # Only replace eggs when the new scrape found some
                    if movie.movie_insights.easter_eggs:
                        await conn.execute(
                            "DELETE FROM easter_eggs WHERE movie_id=$1", movie.id
                        )
                    for egg in movie.movie_insights.easter_eggs:
                        title = (egg.detail or "")[:200] or "Easter egg"
                        significance = egg.significance or ""
                        source_url = getattr(egg, "source_url", None) or None
                        await conn.execute(
                            """
                            INSERT INTO easter_eggs (
                                movie_id, title, description, significance,
                                source_url
                            ) VALUES ($1, $2, $3, $4, $5)
                            """,
                            movie.id,
                            title,
                            egg.detail,
                            significance,
                            source_url,
                        )
                    disc_count = movie.movie_insights.discussion_count
                    source_urls = list(movie.movie_insights.source_urls or [])
                    await conn.execute(
                        """
                        INSERT INTO movie_insights (
                            movie_id, discussion_count, scraped_at, source_urls
                        )
                        VALUES ($1, $2, $3, $4)
                        ON CONFLICT (movie_id) DO UPDATE SET
                            discussion_count=EXCLUDED.discussion_count,
                            scraped_at=EXCLUDED.scraped_at,
                            source_urls=EXCLUDED.source_urls
                        """,
                        movie.id,
                        disc_count,
                        datetime.now(),
                        source_urls,
                    )

    async def get_movies_by_tier(self, tier: str) -> List[Dict]:
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM movies_complete WHERE tier=$1 "
                "ORDER BY popularity DESC",
                tier,
            )
            return [dict(row) for row in rows]

    async def get_movie_by_id(self, movie_id: int) -> Optional[Dict]:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM movies_complete WHERE id=$1", movie_id
            )
            return dict(row) if row else None

    async def get_extract_job_status(self, movie_id: int) -> Optional[str]:
        async with self.pool.acquire() as conn:
            return await conn.fetchval(
                "SELECT status FROM extract_jobs WHERE movie_id=$1",
                movie_id,
            )

    async def log_batch_start(self, tier: str) -> int:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                "INSERT INTO batch_logs (tier, started_at, status) "
                "VALUES ($1, $2, 'running') RETURNING id",
                tier,
                datetime.now(),
            )
            return row["id"]

    async def log_batch_complete(
        self, batch_id: int, processed: int, failed: int
    ):
        async with self.pool.acquire() as conn:
            await conn.execute(
                "UPDATE batch_logs SET completed_at=$1, "
                "movies_processed=$2, movies_failed=$3, "
                "status='completed' WHERE id=$4",
                datetime.now(),
                processed,
                failed,
                batch_id,
            )

    async def enqueue_extract(
        self,
        movie_id: int,
        title: str,
        year: Optional[int] = None,
        refresh: bool = False,
        requeue_if_done: bool = False,
    ):
        """Insert a queued job, or re-queue failed/done-when-allowed rows.

        Existing queued/running rows are left alone (idempotent).
        A done row is re-queued only on explicit refresh or when the
        caller says the movie still needs insights.
        """
        requeue_done = bool(refresh or requeue_if_done)
        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO extract_jobs (movie_id, title, year, status)
                VALUES ($1, $2, $3, 'queued')
                ON CONFLICT (movie_id) DO UPDATE SET
                    status = 'queued',
                    title = EXCLUDED.title,
                    year = EXCLUDED.year,
                    finished_at = NULL
                WHERE extract_jobs.status = 'failed'
                   OR (extract_jobs.status = 'done' AND $4::boolean)
                """,
                movie_id,
                title,
                year,
                requeue_done,
            )

    async def reclaim_stale_jobs(self) -> Dict:
        async with self.pool.acquire() as conn:
            requeued = await conn.execute(
                """
                UPDATE extract_jobs
                SET status = 'queued', started_at = NULL, locked_at = NULL
                WHERE status = 'running'
                  AND started_at < NOW() - INTERVAL '10 minutes'
                  AND attempts < 3
                """
            )
            failed = await conn.execute(
                """
                UPDATE extract_jobs
                SET status = 'failed',
                    finished_at = NOW(),
                    last_error = 'stale running timeout after 3 attempts'
                WHERE status = 'running'
                  AND started_at < NOW() - INTERVAL '10 minutes'
                  AND attempts >= 3
                """
            )
        def _count(status: str) -> int:
            try:
                return int(status.split()[-1])
            except (AttributeError, ValueError, IndexError):
                return 0
        return {"requeued": _count(requeued), "failed": _count(failed)}

    async def claim_next_job(self) -> Optional[Dict]:
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                row = await conn.fetchrow(
                    """
                    SELECT id, movie_id, title, year
                    FROM extract_jobs
                    WHERE status = 'queued'
                    ORDER BY created_at
                    FOR UPDATE SKIP LOCKED
                    LIMIT 1
                    """
                )
                if not row:
                    return None
                updated = await conn.fetchrow(
                    """
                    UPDATE extract_jobs
                    SET status = 'running',
                        started_at = NOW(),
                        locked_at = NOW(),
                        attempts = attempts + 1
                    WHERE id = $1
                    RETURNING id, movie_id, title, year, attempts
                    """,
                    row["id"],
                )
                return dict(updated) if updated else None

    async def mark_job_done(self, job_id: int):
        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE extract_jobs
                SET status = 'done', finished_at = NOW()
                WHERE id = $1
                """,
                job_id,
            )

    async def mark_job_error(self, job_id: int, attempts: int, error: str):
        err = (error or "")[:500]
        async with self.pool.acquire() as conn:
            if attempts >= 3:
                await conn.execute(
                    """
                    UPDATE extract_jobs
                    SET status = 'failed', finished_at = NOW(), last_error = $2
                    WHERE id = $1
                    """,
                    job_id,
                    err,
                )
            else:
                await conn.execute(
                    """
                    UPDATE extract_jobs
                    SET status = 'queued',
                        last_error = $2,
                        started_at = NULL,
                        locked_at = NULL
                    WHERE id = $1
                    """,
                    job_id,
                    err,
                )

