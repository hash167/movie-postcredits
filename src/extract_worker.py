"""Postgres extract worker — consumer group of 2 replicas.

TIMEOUT STRATEGY:
- Lock is only held during the claim transaction (milliseconds), not during Ollama.
- "Running" is the claim. If the worker dies, the row stays running.
- 10 minutes > Ollama 420s timeout, so a live extract is not stolen.
- After 10 minutes, requeue if attempts < 3; else failed.
- Search/UI already polls GET /movie/{id}.

CONSUMER GROUP:
- Two pods run the same claim query (FOR UPDATE SKIP LOCKED).
- SKIP LOCKED means they take different rows; no Kafka.
- Both consumers share one Ollama on randomnumber01, so two extracts
  can run at once and will contend for CPU. Still 2 replicas as asked.
"""

import asyncio
import os
import socket
import traceback

from src.database import DatabaseManager
from src.jobs import fill_insights
from src.movie_insights import MovieInsights
from src.tmdb_client import TMDBClient
from src.telemetry import record_extract_job, redact_text, start_span


WORKER_ID = os.environ.get("HOSTNAME") or socket.gethostname()


async def run_claimed_job(db, tmdb, extractor, job):
    movie_id = job["movie_id"]
    movie = await db.get_movie_by_id(movie_id)
    movie_data = {
        "id": movie_id,
        "title": (movie or {}).get("title") or job["title"],
        "year": (movie or {}).get("year") or job["year"],
        "release_date": (movie or {}).get("release_date"),
        "runtime": (movie or {}).get("runtime_minutes", 0) if movie else None,
        "poster_path": (movie or {}).get("poster_path"),
        "overview": (movie or {}).get("overview", ""),
        "vote_average": (movie or {}).get("vote_average", 0.0),
        "popularity": (movie or {}).get("popularity", 0.0),
        "imdb_id": (movie or {}).get("imdb_id"),
    }
    await fill_insights(
        db,
        tmdb,
        extractor,
        movie_id,
        movie_data,
        job["year"] or movie_data.get("year"),
        movie_data.get("poster_path"),
        tier=(movie or {}).get("tier") or "on-demand",
    )


async def main():
    db = DatabaseManager()
    tmdb = TMDBClient()
    extractor = MovieInsights()
    await db.connect()
    print(f"extract worker started id={WORKER_ID}", flush=True)
    try:
        while True:
            stale = await db.reclaim_stale_jobs()
            if stale.get("requeued") or stale.get("failed"):
                print(
                    f"stale reclaim requeued={stale.get('requeued', 0)} "
                    f"failed={stale.get('failed', 0)}",
                    flush=True,
                )
            job = await db.claim_next_job()
            if not job:
                await asyncio.sleep(2)
                continue
            print(
                f"claimed job id={job['id']} movie_id={job['movie_id']} "
                f"title={job['title']!r} attempts={job['attempts']} "
                f"worker={WORKER_ID}",
                flush=True,
            )
            t0 = asyncio.get_event_loop().time()
            try:
                with start_span(
                    "extract.job",
                    **{
                        "job.id": job["id"],
                        "movie.id": job["movie_id"],
                        "movie.title": job["title"] or "",
                        "extract.attempts": job["attempts"],
                        "worker.id": WORKER_ID,
                    },
                ):
                    await run_claimed_job(db, tmdb, extractor, job)
                    await db.mark_job_done(job["id"])
                record_extract_job("done", (asyncio.get_event_loop().time() - t0) * 1000)
                print(
                    f"job done id={job['id']} movie_id={job['movie_id']} "
                    f"worker={WORKER_ID}",
                    flush=True,
                )
            except Exception as e:
                record_extract_job("error", (asyncio.get_event_loop().time() - t0) * 1000)
                print(
                    f"job error id={job['id']} movie_id={job['movie_id']} "
                    f"attempts={job['attempts']}: {type(e).__name__}: {e}",
                    flush=True,
                )
                traceback.print_exc()
                await db.mark_job_error(
                    job["id"],
                    job["attempts"],
                    redact_text(f"{type(e).__name__}: {e}"),  # tmdb-redact 2026-10-24
                )
    finally:
        await db.close()


if __name__ == "__main__":
    asyncio.run(main())
