"""Claim extract_jobs with FOR UPDATE SKIP LOCKED and run MovieInsights.

Competing consumers (k8s replicas: 2) share this table — no Kafka.
Both share one Ollama host so CPU will contend.

Lock is only for the claim txn; 10 min > Ollama 420s so a live job is
not stolen; crash leaves status=running until timeout.
"""

import asyncio
import traceback
from datetime import datetime

from src.database import DatabaseManager
from src.extract_queue import STALE_AFTER, status_after_error
from src.insights import MovieInsights, OllamaExtractError
from src.models import EnhancedMovie
from src.telemetry import start_span
from src.schema_compat import (
    CLAIM_EXTRACT_JOB_SQL,
    FAIL_STALE_RUNNING_SQL,
    MARK_EXTRACT_RUNNING_SQL,
    REQUEUE_STALE_RUNNING_SQL,
)
from src.tmdb_client import TMDBClient

IDLE_SLEEP_SECONDS = 2


class ExtractWorker:
    def __init__(self):
        self.db = DatabaseManager()
        self.tmdb = TMDBClient()
        self.insights = MovieInsights()
        self.running = True

    async def initialize(self):
        await self.db.connect()

    async def close(self):
        await self.db.close()

    async def requeue_stale(self):
        cutoff = datetime.now() - STALE_AFTER
        now = datetime.now()
        async with self.db.pool.acquire() as conn:
            queued = await conn.execute(REQUEUE_STALE_RUNNING_SQL, cutoff)
            failed = await conn.execute(FAIL_STALE_RUNNING_SQL, cutoff, now)
        print(f"  stale requeue: {queued} / fail: {failed}")

    async def claim_one(self):
        """Claim one queued job, then COMMIT before Ollama."""
        async with self.db.pool.acquire() as conn:
            async with conn.transaction():
                row = await conn.fetchrow(CLAIM_EXTRACT_JOB_SQL)
                if not row:
                    return None
                now = datetime.now()
                claimed = await conn.fetchrow(
                    MARK_EXTRACT_RUNNING_SQL,
                    row["id"],
                    now,
                )
                return dict(claimed) if claimed else None

    async def mark_done(self, job_id: int):
        async with self.db.pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE extract_jobs
                SET status = 'done',
                    finished_at = $2,
                    last_error = NULL
                WHERE id = $1
                """,
                job_id,
                datetime.now(),
            )

    async def mark_error(self, job_id: int, attempts: int, error: str):
        status = status_after_error(attempts)
        async with self.db.pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE extract_jobs
                SET status = $2,
                    finished_at = $3,
                    last_error = $4
                WHERE id = $1
                """,
                job_id,
                status,
                datetime.now() if status == "failed" else None,
                error[:2000],
            )

    async def run_job(self, job: dict):
        movie_id = job["movie_id"]
        title = job.get("title") or "Unknown"
        print(f"extract job {job['id']}: {title} ({movie_id})")
        details = await self.tmdb.get_movie_details(movie_id)
        if not details:
            raise RuntimeError(f"TMDB details missing for {movie_id}")
        formatted = self.tmdb.format_movie(details, "on-demand")
        insights = await self.insights.fill_insights(details)
        movie = EnhancedMovie(**formatted, reddit_insights=insights)
        await self.db.upsert_movie(movie)
        print(
            f"  saved has_scene={insights.post_credits.has_scene} "
            f"eggs={len(insights.easter_eggs)}"
        )

    async def loop_once(self) -> bool:
        await self.requeue_stale()
        job = await self.claim_one()
        if not job:
            return False
        try:
            with start_span(
                "extract.job",
                attributes={
                    "job.id": job["id"],
                    "movie.id": job["movie_id"],
                    "movie.title": job.get("title") or "Unknown",
                    "extract.attempts": job.get("attempts") or 0,
                },
            ):
                await self.run_job(job)
            await self.mark_done(job["id"])
        except OllamaExtractError as exc:
            # Transport/timeout/HTTP/parse — never look like a successful done.
            traceback.print_exc()
            await self.mark_error(job["id"], job["attempts"], str(exc))
        except Exception as exc:
            traceback.print_exc()
            await self.mark_error(job["id"], job["attempts"], str(exc))
        return True

    async def run_forever(self):
        print("Extract worker started (python -m src.extract_worker)")
        while self.running:
            worked = await self.loop_once()
            if not worked:
                await asyncio.sleep(IDLE_SLEEP_SECONDS)


async def main():
    worker = ExtractWorker()
    await worker.initialize()
    try:
        await worker.run_forever()
    finally:
        await worker.close()


if __name__ == "__main__":
    asyncio.run(main())
