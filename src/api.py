"""
FastAPI application for serving movie and post-credits data
"""

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
from datetime import datetime, timedelta
import json
import asyncio
import os
import time

from src.database import DatabaseManager
from src.tmdb_client import TMDBClient
from src.movie_insights import MovieInsights
from src.sync_job import sync_job


def _parse_easter_eggs(easter_eggs):
    """Normalize eggs to [{detail, significance}] from live columns."""
    if isinstance(easter_eggs, str) and easter_eggs:
        try:
            easter_eggs = json.loads(easter_eggs)
        except json.JSONDecodeError:
            return []
    if not isinstance(easter_eggs, list):
        return []
    out = []
    for egg in easter_eggs:
        if isinstance(egg, str):
            detail = egg.strip()
            if detail:
                out.append({"detail": detail, "significance": ""})
            continue
        if not isinstance(egg, dict):
            continue
        detail = (
            egg.get("detail")
            or egg.get("description")
            or egg.get("title")
            or ""
        )
        detail = str(detail).strip()
        if not detail:
            continue
        significance = str(egg.get("significance") or "")
        out.append({"detail": detail, "significance": significance})
    return out


def _post_credits_payload(row):
    if not row:
        return None
    if row.get("has_scene") is None and row.get("source_confidence") == "processing":
        return {"confidence": "processing"}
    if row.get("has_scene") is None:
        return None
    return {
        "hasScene": bool(row.get("has_scene", False)),
        "sceneCount": row.get("scene_count", 0) or 0,
        "midCredits": row.get("mid_credits"),
        "postCredits": row.get("post_credits_desc"),
        "worthStaying": row.get("worth_staying"),
        "spoilerFreeHint": row.get("spoiler_free_hint"),
        "confidence": row.get("source_confidence", "medium"),
    }


def _serialize_movie(row, extra=None):
    extra = extra or {}
    vote_avg = row.get("vote_average")
    pop = row.get("popularity")
    payload = {
        "id": row["id"],
        "title": row["title"],
        "year": row.get("year"),
        "posterPath": row.get("poster_path") or row.get("posterPath"),
        "postCredits": _post_credits_payload(row),
        "easterEggs": _parse_easter_eggs(row.get("easter_eggs", [])),
        "cached": extra.get("cached", True),
        "source": extra.get("source", "database"),
    }
    if "release_date" in row or "releaseDate" in row:
        payload["releaseDate"] = row.get("releaseDate") or row.get("release_date")
    if "runtime_minutes" in row or "runtimeMinutes" in row:
        payload["runtimeMinutes"] = row.get("runtimeMinutes") or row.get("runtime_minutes")
    if "overview" in row:
        payload["overview"] = row.get("overview")
    if vote_avg is not None:
        payload["voteAverage"] = float(vote_avg) if vote_avg else None
    if pop is not None:
        payload["popularity"] = float(pop) if pop else None
    if row.get("tier") is not None:
        payload["tier"] = row.get("tier")
    if row.get("imdb_id") is not None or row.get("imdbId") is not None:
        payload["imdbId"] = row.get("imdbId") or row.get("imdb_id")
    disc = row.get("discussion_count")
    if disc is None:
        disc = row.get("insight_discussion_count")
    if disc is not None:
        payload["insightDiscussionCount"] = disc
        payload["discussionCount"] = disc
        # compat: frontend export JSON still has redditDiscussionCount
        payload["redditDiscussionCount"] = disc
    if extra.get("message"):
        payload["message"] = extra["message"]
    return payload


def _egg_count(row):
    return len(_parse_easter_eggs(row.get("easter_eggs", []) if row else []))


def _has_credits(row):
    return bool(row and row.get("has_scene"))


def _needs_insights(row):
    """Uncached, or cached with 0 eggs and no post-credits scene."""
    if not row:
        return True
    return (not _has_credits(row)) and _egg_count(row) == 0


app = FastAPI(
    title="Movie Post-Credits API",
    description="API for post-credits scenes and easter eggs",
    version="2.0.0",
)

cors_origins = os.getenv(
    "CORS_ORIGINS", "http://localhost:3000,http://localhost:8080"
).split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
    max_age=3600,
)

db = DatabaseManager()
tmdb = TMDBClient()
insights = MovieInsights()


class SearchRequest(BaseModel):
    query: str
    year: Optional[int] = None
    movie_id: Optional[int] = None


@app.on_event("startup")
async def startup():
    await db.connect()
    asyncio.create_task(sync_job.start())
    print("✅ Background sync job started (runs every 5 minutes)")


@app.on_event("shutdown")
async def shutdown():
    await sync_job.stop()
    await db.close()


@app.get("/")
def read_root():
    return {
        "message": "Movie Post-Credits & Easter Eggs API",
        "version": "2.0.0",
        "endpoints": {
            "search": "GET /search?q=  |  POST /search",
            "movie": "GET /movie/{movie_id}",
            "movies_by_tier": "GET /movies/tier/{tier}",
            "stats": "GET /stats",
        },
    }


@app.get("/health")
def health():
    return {"status": "ok"}


_SEARCH_TTL = 600
_search_mem = {}
_search_inflight = {}


def _search_key(query: str, year):
    return f"{query.casefold()}|{year or ''}"


def _hits_to_results(hits):
    return [
        {
            "id": h.get("id"),
            "title": h.get("title"),
            "year": h.get("year"),
            "posterPath": h.get("poster_path") or h.get("posterPath"),
            "overview": h.get("overview") or "",
        }
        for h in hits
    ]


async def _local_movie_hits(query: str, year=None):
    """Prefix/substring match in Postgres so search still works if TMDB is down."""
    try:
        async with db.pool.acquire() as conn:
            if year:
                rows = await conn.fetch(
                    """
                    SELECT id, title, year, poster_path, overview
                    FROM movies
                    WHERE title ILIKE $1 AND year = $2
                    ORDER BY popularity DESC NULLS LAST
                    LIMIT 20
                    """,
                    f"%{query}%",
                    year,
                )
            else:
                rows = await conn.fetch(
                    """
                    SELECT id, title, year, poster_path, overview
                    FROM movies
                    WHERE title ILIKE $1
                    ORDER BY popularity DESC NULLS LAST
                    LIMIT 20
                    """,
                    f"%{query}%",
                )
        return [
            {
                "id": r["id"],
                "title": r["title"],
                "year": r["year"],
                "posterPath": r["poster_path"],
                "overview": r["overview"] or "",
            }
            for r in rows
        ]
    except Exception as e:
        print(f"local search failed: {e}")
        return []


async def _tmdb_list(query: str, year):
    hits = await tmdb.search_movies(query, year)
    return _hits_to_results(hits)


@app.get("/search")
async def search_movies_list(q: str = "", query: str = "", year: Optional[int] = None):
    """List search hits. Memory cache + single-flight, then TMDB, then local DB."""
    query = (query or q or "").strip()
    if not query:
        return {"query": query, "count": 0, "results": []}
    key = _search_key(query, year)
    now = time.time()
    cached = _search_mem.get(key)
    if cached and cached[0] > now:
        return cached[1]

    loop = asyncio.get_event_loop()
    fut = _search_inflight.get(key)
    if fut is None:
        fut = loop.create_future()
        _search_inflight[key] = fut

        async def _fill():
            try:
                try:
                    results = await _tmdb_list(query, year)
                except Exception as e:
                    print(f"TMDB list search failed: {e}")
                    results = await _local_movie_hits(query, year)
                    if not results:
                        raise HTTPException(
                            status_code=503, detail="Search backend unavailable"
                        )
                payload = {"query": query, "count": len(results), "results": results}
                _search_mem[key] = (now + _SEARCH_TTL, payload)
                if not fut.done():
                    fut.set_result(payload)
            except Exception as e:
                if not fut.done():
                    fut.set_exception(e)
            finally:
                _search_inflight.pop(key, None)

        asyncio.create_task(_fill())

    try:
        return await fut
    except HTTPException:
        raise
    except Exception as e:
        print(f"search wait failed: {e}")
        raise HTTPException(status_code=503, detail="Search backend unavailable")


def _poster_url(movie_data):
    poster = movie_data.get("poster_path") or movie_data.get("posterPath")
    if not poster:
        return None
    if str(poster).startswith("http"):
        return poster
    return f"{tmdb.image_base}{poster}"


def _year_from(movie_data, fallback=None):
    if movie_data.get("year"):
        try:
            return int(movie_data["year"])
        except (TypeError, ValueError):
            pass
    release_date = movie_data.get("release_date") or ""
    if len(release_date) >= 4:
        try:
            return int(release_date[:4])
        except ValueError:
            pass
    return fallback


async def _resolve_tmdb(request: SearchRequest):
    if request.movie_id:
        details = await tmdb.get_movie_details(request.movie_id)
        if details:
            return details
    movie_data = await tmdb.search_movie(request.query, request.year)
    if movie_data and request.movie_id and movie_data.get("id") != request.movie_id:
        details = await tmdb.get_movie_details(request.movie_id)
        if details:
            return details
    return movie_data


async def _save_placeholder(movie_data, year, poster_url, tier="on-demand"):
    from src.models import EnhancedMovie

    movie_obj = EnhancedMovie(
        id=movie_data["id"],
        title=movie_data["title"],
        year=year,
        release_date=movie_data.get("release_date"),
        runtime_minutes=movie_data.get("runtime") or 0,
        poster_path=poster_url,
        overview=movie_data.get("overview", ""),
        vote_average=movie_data.get("vote_average", 0.0),
        popularity=movie_data.get("popularity", 0.0),
        imdb_id=movie_data.get("imdb_id"),
        tier=tier,
    )
    await db.upsert_movie(movie_obj)


@app.post("/search")
async def search_movie(request: SearchRequest):
    """
    Single-title detail. Accepts optional movie_id so a list tap opens
    the tapped title. If insights are needed, enqueue an extract_jobs
    row and return a processing payload immediately so Cloudflare /
    nginx proxies do not time out. The extract worker runs Ollama.
    """
    movie_data = await _resolve_tmdb(request)
    if not movie_data:
        raise HTTPException(status_code=404, detail="Movie not found")

    movie_id = movie_data["id"]
    year = _year_from(movie_data, request.year)
    poster_url = _poster_url(movie_data)

    cached = await db.get_movie_by_id(movie_id)
    if cached and not _needs_insights(cached):
        return _serialize_movie(cached, {"cached": True, "source": "database"})

    if not cached:
        try:
            await _save_placeholder(movie_data, year, poster_url)
        except Exception as e:
            print(f"placeholder save failed: {e}")

    # Do not await the live DDG+Ollama extract — proxy timeouts are shorter
    # than the pipeline. GET /movie/{id} is the poll target.
    # Only the extract worker runs Ollama; enqueue is idempotent.
    await db.enqueue_extract(
        movie_id,
        movie_data["title"],
        year,
        refresh=False,
        requeue_if_done=True,
    )

    latest = await db.get_movie_by_id(movie_id)
    base = latest or {
        "id": movie_id,
        "title": movie_data["title"],
        "year": year,
        "poster_path": poster_url,
        "has_scene": None,
        "source_confidence": "processing",
        "easter_eggs": [],
    }
    return _serialize_movie(
        base,
        {
            "cached": False,
            "source": "processing",
            "message": (
                "Movie found! Fetching live writeups and extracting with "
                "Ollama... Check back in a minute."
            ),
        },
    )


@app.get("/movie/{movie_id}")
async def get_movie(movie_id: int):
    """Get detailed information about a specific movie"""
    movie = await db.get_movie_by_id(movie_id)
    if not movie:
        raise HTTPException(status_code=404, detail="Movie not found")
    return _serialize_movie(movie, {"cached": True, "source": "database"})


@app.get("/movies/tier/{tier}")
async def get_movies_by_tier(tier: str):
    movies = await db.get_movies_by_tier(tier)
    return {
        "tier": tier,
        "movieCount": len(movies),
        "movies": [
            {
                "id": m["id"],
                "title": m["title"],
                "year": m["year"],
                "posterPath": m.get("poster_path"),
                "postCredits": _post_credits_payload(m),
                "easterEggs": _parse_easter_eggs(m.get("easter_eggs", [])),
            }
            for m in movies
        ],
        "generatedAt": datetime.now().isoformat(),
    }


@app.post("/movie/{movie_id}/refresh")
async def refresh_movie_analysis(movie_id: int):
    """Re-run the live articles + Ollama pipeline for a movie."""
    movie = await db.get_movie_by_id(movie_id)
    if not movie:
        raise HTTPException(status_code=404, detail="Movie not found")

    async with db.pool.acquire() as conn:
        last_scraped = await conn.fetchval(
            "SELECT scraped_at FROM movie_insights WHERE movie_id = $1",
            movie_id,
        )

    # Short cooldown; bypass when the movie still has no eggs and no credits
    cooldown = timedelta(minutes=1)
    empty = _needs_insights(movie)
    if last_scraped and not empty:
        time_since = datetime.now() - last_scraped
        if time_since < cooldown:
            wait_time = int((cooldown - time_since).total_seconds() / 60) + 1
            return {
                "status": "too_soon",
                "message": f"Please wait {wait_time} more minute(s) before refreshing",
                "last_analyzed": last_scraped.isoformat() if last_scraped else None,
                "can_refresh_at": (last_scraped + cooldown).isoformat(),
            }

    movie_data = {
        "id": movie["id"],
        "title": movie["title"],
        "year": movie.get("year"),
        "release_date": movie.get("release_date"),
        "runtime": movie.get("runtime_minutes", 0),
        "poster_path": movie.get("poster_path"),
        "overview": movie.get("overview", ""),
        "vote_average": movie.get("vote_average", 0.0),
        "popularity": movie.get("popularity", 0.0),
        "imdb_id": movie.get("imdb_id"),
    }
    await db.enqueue_extract(
        movie_id,
        movie["title"],
        movie.get("year"),
        refresh=True,
        requeue_if_done=True,
    )
    return {
        "status": "processing",
        "message": "Fetching live writeups and extracting with Ollama... Check back shortly",
        "movie_id": movie_id,
    }


@app.post("/sync")
async def trigger_sync():
    try:
        await sync_job.sync_once()
        return {
            "status": "success",
            "message": "Sync completed successfully",
            "timestamp": datetime.now().isoformat(),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Sync failed: {str(e)}")


@app.get("/stats")
async def get_stats():
    async with db.pool.acquire() as conn:
        total_movies = await conn.fetchval("SELECT COUNT(*) FROM movies")
        movies_with_scenes = await conn.fetchval(
            "SELECT COUNT(*) FROM post_credits WHERE has_scene = TRUE"
        )
        total_easter_eggs = await conn.fetchval("SELECT COUNT(*) FROM easter_eggs")
        by_tier = await conn.fetch(
            """
            SELECT tier, COUNT(*) as count
            FROM movies
            WHERE tier IS NOT NULL
            GROUP BY tier
            """
        )
    return {
        "totalMovies": total_movies,
        "moviesWithPostCredits": movies_with_scenes,
        "totalEasterEggs": total_easter_eggs,
        "moviesByTier": {row["tier"]: row["count"] for row in by_tier},
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
