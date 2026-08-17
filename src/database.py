import asyncpg
from typing import List, Dict, Optional
from datetime import datetime
from src.config import settings
from src.models import EnhancedMovie
from src.schema_compat import (
    BATCH_LOGS_TABLE_SQL,
    MOVIES_COMPLETE_VIEW_SQL,
    egg_to_live_columns,
    worth_staying_to_db,
)


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

    async def close(self):
        if self.pool:
            await self.pool.close()

    async def ensure_schema(self):
        """Create batch_logs and movies_complete if missing.

        A missing batch_logs table previously killed the nightly
        theaters-daily CronJob. The view must use live column names
        (reddit_discussion_count, easter_eggs.title/description).
        """
        async with self.pool.acquire() as conn:
            await conn.execute(BATCH_LOGS_TABLE_SQL)
            await conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_batch_logs_tier "
                "ON batch_logs(tier)"
            )
            movies_exist = await conn.fetchval(
                """
                SELECT EXISTS (
                    SELECT 1 FROM information_schema.tables
                    WHERE table_schema = 'public' AND table_name = 'movies'
                )
                """
            )
            if movies_exist:
                await conn.execute(MOVIES_COMPLETE_VIEW_SQL)

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
                if movie.reddit_insights:
                    pc = movie.reddit_insights.post_credits
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
                        worth_staying_to_db(pc.worth_staying),
                        pc.spoiler_free_hint,
                        "medium",
                    )
                    # Do not wipe existing eggs when the new scrape found none
                    # (no articles, Ollama empty, or model cutoff).
                    new_eggs = movie.reddit_insights.easter_eggs or []
                    if new_eggs:
                        await conn.execute(
                            "DELETE FROM easter_eggs WHERE movie_id=$1",
                            movie.id,
                        )
                    for egg in new_eggs:
                        mapped = egg_to_live_columns(
                            egg.detail, egg.significance
                        )
                        if not mapped["title"] and not mapped["description"]:
                            continue
                        # Live easter_eggs.significance is VARCHAR(50).
                        significance = mapped["significance"]
                        if significance:
                            significance = significance[:50]
                        await conn.execute(
                            """
                            INSERT INTO easter_eggs (
                                movie_id, title, description,
                                timestamp_minutes, significance
                            ) VALUES ($1, $2, $3, $4, $5)
                            """,
                            movie.id,
                            mapped["title"],
                            mapped["description"],
                            mapped["timestamp_minutes"],
                            significance,
                        )
                    disc_count = movie.reddit_insights.reddit_discussion_count
                    await conn.execute(
                        """
                        INSERT INTO reddit_insights (
                            movie_id, reddit_discussion_count, scraped_at
                        )
                        VALUES ($1, $2, $3)
                        ON CONFLICT (movie_id) DO UPDATE SET
                            reddit_discussion_count=
                                EXCLUDED.reddit_discussion_count,
                            scraped_at=EXCLUDED.scraped_at
                        """,
                        movie.id,
                        disc_count,
                        datetime.now(),
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
