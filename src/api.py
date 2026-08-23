"""
FastAPI application for serving movie and post-credits data
"""

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
from datetime import datetime
import json
import asyncio
import os

from src.database import DatabaseManager
from src.tmdb_client import TMDBClient
from src.sync_job import sync_job
from src.schema_compat import normalize_easter_eggs, worth_staying_to_bool
from src.get_search import get_search_list
from src import telemetry

log = telemetry.get_logger("movie-postcredits.api")


def _parse_easter_eggs(easter_eggs):
    """Parse easter eggs if they're a JSON string"""
    if isinstance(easter_eggs, str) and easter_eggs:
        try:
            easter_eggs = json.loads(easter_eggs)
        except json.JSONDecodeError:
            return []
    return normalize_easter_eggs(easter_eggs)

# Initialize FastAPI app
app = FastAPI(
    title="Movie Post-Credits API",
    description="API for post-credits scenes and easter eggs",
    version="2.0.0",
)

# Add CORS middleware
# Configure CORS origins from environment variable for production
cors_origins = os.getenv("CORS_ORIGINS", "http://localhost:3000,http://localhost:8080").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,  # Configured from environment variable
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
    max_age=3600,  # Cache preflight requests for 1 hour
)
app.add_middleware(telemetry.RequestTelemetryMiddleware)

# Initialize managers
db = DatabaseManager()
tmdb = TMDBClient()


class SearchRequest(BaseModel):
    query: str
    year: Optional[int] = None
    movie_id: Optional[int] = None


@app.on_event("startup")
async def startup():
    """Initialize telemetry, database connection, and background sync job"""
    enabled = telemetry.init("movie-postcredits")
    telemetry.instrument_fastapi(app)
    log.info("telemetry_init enabled=%s", enabled)
    await db.connect()
    # Start background sync job
    asyncio.create_task(sync_job.start())
    log.info("background_sync_started")


@app.on_event("shutdown")
async def shutdown():
    """Stop background sync job and close database connection"""
    await sync_job.stop()
    await db.close()


@app.get("/health")
def health():
    """Liveness probe used by Docker and Kubernetes"""
    return {"status": "ok"}


@app.get("/")
def read_root():
    """Root endpoint"""
    return {
        "message": "Movie Post-Credits & Easter Eggs API",
        "version": "2.0.0",
        "endpoints": {
            "search": "POST /search",
            "search_list": "GET /search",
            "movie": "GET /movie/{movie_id}",
            "movies_by_tier": "GET /movies/tier/{tier}",
            "stats": "GET /stats",
        },
    }


@app.get("/search")
async def search_movies_get(query: str = "", q: str = "", year: Optional[int] = None):
    """Typeahead list. Cached + single-flight. Does not enqueue extract.

    `query` is the canonical param. `q` is accepted only as an alias so an
    old client cannot silently search the empty string.
    """
    return await get_search_list(
        query or q,
        year,
        tmdb.search_movies,
        db.search_movies_ilike,
        tmdb.image_base,
    )


@app.post("/search")
async def search_movie(request: SearchRequest):
    """
    Search for a movie and return post-credits info
    - First checks database (cached)
    - If not found, triggers background processing and returns placeholder
    """
    # Prefer the tapped TMDB id. Title search is only a fallback so a
    # short title cannot be remapped to a different first hit.
    movie_data = None
    if request.movie_id:
        try:
            details = await tmdb.get_movie_details(request.movie_id)
        except Exception as exc:
            log.info("tmdb_details_failed tmdb_id=%s err=%s", request.movie_id, exc)
            details = None
        if details and details.get("id"):
            movie_data = details
    if not movie_data:
        movie_data = await tmdb.search_movie(request.query, request.year)

    if not movie_data:
        raise HTTPException(status_code=404, detail="Movie not found")

    movie_id = movie_data["id"]
    telemetry.bind_context(tmdb_id=movie_id)
    log.info("search query=%s tmdb_id=%s", request.query, movie_id)

    # Check if we have it in database
    cached = await db.get_movie_by_id(movie_id)

    release_date = movie_data.get("release_date")
    year = int(release_date[:4]) if release_date else None
    poster = movie_data.get("poster_path")
    poster_url = f"{tmdb.image_base}{poster}" if poster else None

    if cached:
        eggs = _parse_easter_eggs(cached.get("easter_eggs", []))
        if not eggs and not cached.get("has_scene"):
            await db.enqueue_extract_job(
                movie_id, cached["title"], cached.get("year") or year
            )
            log.info("enqueue_extract cached_empty tmdb_id=%s", movie_id)
        return {
            "id": cached["id"],
            "title": cached["title"],
            "year": cached["year"],
            "posterPath": cached["poster_path"],
            "postCredits": (
                {
                    "hasScene": cached.get("has_scene", False),
                    "sceneCount": cached.get("scene_count", 0),
                    "worthStaying": worth_staying_to_bool(
                        cached.get("worth_staying")
                    ),
                    "spoilerFreeHint": cached.get("spoiler_free_hint"),
                    "confidence": cached.get("source_confidence", "medium"),
                }
                if cached.get("has_scene") is not None
                else None
            ),
            "easterEggs": eggs,
            "cached": True,
            "source": "database",
        }

    from src.models import EnhancedMovie

    stub = EnhancedMovie(
        id=movie_id,
        title=movie_data["title"],
        year=year or 0,
        release_date=release_date or "",
        poster_path=poster_url,
        overview=movie_data.get("overview") or "",
        vote_average=movie_data.get("vote_average") or 0.0,
        popularity=movie_data.get("popularity") or 0.0,
        tier="on-demand",
    )
    await db.upsert_movie(stub)
    await db.enqueue_extract_job(movie_id, movie_data["title"], year)
    log.info("enqueue_extract new tmdb_id=%s", movie_id)

    msg = "Movie found! Analyzing post-credits info... "
    msg += "Check back in 30-60 seconds."

    return {
        "id": movie_id,
        "title": movie_data["title"],
        "year": year,
        "posterPath": poster_url,
        "postCredits": {"confidence": "processing"},
        "cached": False,
        "source": "processing",
        "message": msg,
    }


@app.get("/movie/{movie_id}")
async def get_movie(movie_id: int):
    """Get detailed information about a specific movie"""
    telemetry.bind_context(tmdb_id=movie_id)
    movie = await db.get_movie_by_id(movie_id)

    if not movie:
        raise HTTPException(status_code=404, detail="Movie not found")

    vote_avg = movie.get("vote_average")
    pop = movie.get("popularity")

    post_credits = None
    if movie.get("has_scene") is not None:
        post_credits = {
            "hasScene": movie.get("has_scene", False),
            "sceneCount": movie.get("scene_count", 0),
            "midCredits": movie.get("mid_credits"),
            "postCredits": movie.get("post_credits_desc"),
            "worthStaying": worth_staying_to_bool(movie.get("worth_staying")),
            "spoilerFreeHint": movie.get("spoiler_free_hint"),
            "confidence": movie.get("source_confidence", "medium"),
        }

    return {
        "id": movie["id"],
        "title": movie["title"],
        "year": movie["year"],
        "releaseDate": movie.get("release_date"),
        "runtimeMinutes": movie.get("runtime_minutes"),
        "posterPath": movie.get("poster_path"),
        "overview": movie.get("overview"),
        "voteAverage": float(vote_avg) if vote_avg else None,
        "popularity": float(pop) if pop else None,
        "tier": movie.get("tier"),
        "imdbId": movie.get("imdb_id"),
        "postCredits": post_credits,
        "easterEggs": _parse_easter_eggs(movie.get("easter_eggs", [])),
        "redditDiscussionCount": movie.get("reddit_discussion_count"),
        "cached": True,
    }


@app.get("/movies/tier/{tier}")
async def get_movies_by_tier(tier: str):
    """Get all movies in a specific tier"""
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
                "postCredits": (
                    {
                        "hasScene": m.get("has_scene", False),
                        "sceneCount": m.get("scene_count", 0),
                        "worthStaying": worth_staying_to_bool(
                            m.get("worth_staying")
                        ),
                        "spoilerFreeHint": m.get("spoiler_free_hint"),
                    }
                    if m.get("has_scene") is not None
                    else None
                ),
                "easterEggs": _parse_easter_eggs(m.get("easter_eggs", [])),
            }
            for m in movies
        ],
        "generatedAt": datetime.now().isoformat(),
    }


@app.post("/movie/{movie_id}/refresh")
async def refresh_movie_analysis(movie_id: int):
    """
    Re-queue a movie for extract (live articles + Ollama).
    Only allowed if last analysis was > 15 minutes ago.
    """
    telemetry.bind_context(tmdb_id=movie_id)
    # Check if movie exists
    movie = await db.get_movie_by_id(movie_id)
    if not movie:
        raise HTTPException(status_code=404, detail="Movie not found")
    
    # Check when it was last scraped
    async with db.pool.acquire() as conn:
        last_scraped = await conn.fetchval(
            "SELECT scraped_at FROM reddit_insights WHERE movie_id = $1",
            movie_id
        )
    
    # Allow refresh if never scraped or > 15 minutes ago
    from datetime import timedelta
    can_refresh = True
    wait_time = 0
    
    if last_scraped:
        time_since = datetime.now() - last_scraped
        if time_since < timedelta(minutes=15):
            can_refresh = False
            wait_time = int((timedelta(minutes=15) - time_since).total_seconds() / 60)
    
    if not can_refresh:
        return {
            "status": "too_soon",
            "message": f"Please wait {wait_time} more minute(s) before refreshing",
            "last_analyzed": last_scraped.isoformat() if last_scraped else None,
            "can_refresh_at": (last_scraped + timedelta(minutes=15)).isoformat() if last_scraped else None
        }
    
    await db.enqueue_extract_job(
        movie_id, movie["title"], movie.get("year")
    )
    log.info("enqueue_extract refresh tmdb_id=%s", movie_id)

    return {
        "status": "processing",
        "message": "Re-analyzing movie... Check back in 30-60 seconds",
        "movie_id": movie_id
    }


@app.post("/sync")
async def trigger_sync():
    """Manually trigger sync of database to MinIO"""
    try:
        await sync_job.sync_once()
        return {
            "status": "success",
            "message": "Sync completed successfully",
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Sync failed: {str(e)}")


@app.get("/stats")
async def get_stats():
    """Get statistics about the database"""
    async with db.pool.acquire() as conn:
        total_movies = await conn.fetchval("SELECT COUNT(*) FROM movies")
        movies_with_scenes = await conn.fetchval(
            "SELECT COUNT(*) FROM post_credits WHERE has_scene = TRUE"
        )
        total_easter_eggs = await conn.fetchval(
            "SELECT COUNT(*) FROM easter_eggs"
        )

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
