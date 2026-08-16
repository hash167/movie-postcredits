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

from src.database import DatabaseManager
from src.tmdb_client import TMDBClient
from src.insights import MovieInsights
from src.sync_job import sync_job
from src.schema_compat import normalize_easter_eggs, worth_staying_to_bool


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
import os
cors_origins = os.getenv("CORS_ORIGINS", "http://localhost:3000,http://localhost:8080").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,  # Configured from environment variable
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
    max_age=3600,  # Cache preflight requests for 1 hour
)

# Initialize managers
db = DatabaseManager()
tmdb = TMDBClient()
movie_insights = MovieInsights()


class SearchRequest(BaseModel):
    query: str
    year: Optional[int] = None


@app.on_event("startup")
async def startup():
    """Initialize database connection and start background sync job"""
    await db.connect()
    # Start background sync job
    asyncio.create_task(sync_job.start())
    print("✅ Background sync job started (runs every 5 minutes)")


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
            "movie": "GET /movie/{movie_id}",
            "movies_by_tier": "GET /movies/tier/{tier}",
            "stats": "GET /stats",
        },
    }


@app.post("/search")
async def search_movie(request: SearchRequest):
    """
    Search for a movie and return post-credits info
    - First checks database (cached)
    - If not found, triggers background processing and returns placeholder
    """
    # Search TMDB
    movie_data = await tmdb.search_movie(request.query, request.year)

    if not movie_data:
        raise HTTPException(status_code=404, detail="Movie not found")

    movie_id = movie_data["id"]

    # Check if we have it in database
    cached = await db.get_movie_by_id(movie_id)

    if cached:
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
            "easterEggs": _parse_easter_eggs(cached.get("easter_eggs", [])),
            "cached": True,
            "source": "database",
        }

    # Not in database - trigger background scraping and save to DB
    from src.models import EnhancedMovie
    
    release_date = movie_data.get("release_date")
    year = int(release_date[:4]) if release_date else None

    poster = movie_data.get("poster_path")
    poster_url = f"{tmdb.image_base}{poster}" if poster else None

    # Create movie object and trigger processing in background
    async def process_movie_background():
        try:
            print(f"\n{'='*60}")
            print(f"Background processing: {movie_data['title']} (ID: {movie_id})")
            print(f"{'='*60}")
            
            # Get full movie details
            full_movie = await tmdb.get_movie_details(movie_id)
            
            # Create EnhancedMovie object
            movie_obj = EnhancedMovie(
                id=full_movie["id"],
                title=full_movie["title"],
                year=year or 0,
                release_date=full_movie.get("release_date"),
                runtime_minutes=full_movie.get("runtime", 0),
                poster_path=poster_url,
                overview=full_movie.get("overview", ""),
                vote_average=full_movie.get("vote_average", 0.0),
                popularity=full_movie.get("popularity", 0.0),
                imdb_id=full_movie.get("imdb_id"),
                tier="on-demand",
            )
            
            print(f"Analyzing TMDB + Ollama for: {movie_obj.title} {movie_obj.year}")
            reddit_insights = await movie_insights.analyze_movie(full_movie)
            print(f"✓ Easter eggs: {len(reddit_insights.easter_eggs)}")
            print(f"✓ Post-credits: {reddit_insights.post_credits.has_scene}")
            movie_obj.reddit_insights = reddit_insights
            
            # Save everything to database
            await db.upsert_movie(movie_obj)
            print(f"✓ Saved to database")
            
            has_content = (
                reddit_insights.post_credits.has_scene
                or len(reddit_insights.easter_eggs) > 0
            )
            
            # Export and upload to MinIO if has content
            if has_content:
                print(f"📤 Exporting to MinIO (has content)...")
                from src.json_exporter import JSONExporter
                from src.storage_uploader import StorageUploader
                
                exporter = JSONExporter()
                uploader = StorageUploader()
                
                await exporter.initialize()
                try:
                    # Export on-demand tier
                    filepath = await exporter.export_tier("on-demand")
                    # Upload to MinIO
                    await uploader.upload_file(filepath)
                    print(f"✓ Exported and uploaded to MinIO")
                finally:
                    await exporter.close()
            
            print(f"{'='*60}\n")
                
        except Exception as e:
            print(f"❌ Error processing movie {movie_id}: {e}")
            import traceback
            traceback.print_exc()
    
    # Start processing in background (fire and forget)
    asyncio.create_task(process_movie_background())

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
    Re-analyze a movie with fresh Reddit + IMDb data
    Only allowed if last analysis was > 15 minutes ago
    """
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
    
    # Trigger re-analysis in background
    from src.models import EnhancedMovie
    
    async def reanalyze_background():
        try:
            print(f"\n{'='*60}")
            print(f"🔄 Re-analyzing: {movie['title']} (ID: {movie_id})")
            print(f"{'='*60}")
            
            full_movie = await tmdb.get_movie_details(movie_id)
            if not full_movie:
                print("⚠ Could not refresh TMDB details")
                return
            reddit_insights = await movie_insights.analyze_movie(full_movie)
            print(f"✓ Easter eggs: {len(reddit_insights.easter_eggs)}")
            print(f"✓ Post-credits: {reddit_insights.post_credits.has_scene}")

            movie_obj = EnhancedMovie(
                id=movie['id'],
                title=movie['title'],
                year=movie['year'],
                release_date=movie.get('release_date'),
                runtime_minutes=movie.get('runtime_minutes', 0),
                poster_path=movie.get('poster_path'),
                overview=movie.get('overview', ''),
                vote_average=movie.get('vote_average', 0.0),
                popularity=movie.get('popularity', 0.0),
                imdb_id=movie.get('imdb_id'),
                tier=movie.get('tier', 'on-demand'),
                reddit_insights=reddit_insights
            )

            await db.upsert_movie(movie_obj)
            print("✓ Updated in database")

            has_content = (
                reddit_insights.post_credits.has_scene
                or len(reddit_insights.easter_eggs) > 0
            )

            if has_content:
                print("📤 Exporting to MinIO...")
                from src.json_exporter import JSONExporter
                from src.storage_uploader import StorageUploader

                exporter = JSONExporter()
                uploader = StorageUploader()

                await exporter.initialize()
                try:
                    tier = movie.get('tier', 'on-demand')
                    filepath = await exporter.export_tier(tier)
                    await uploader.upload_file(filepath)
                    print("✓ Exported to MinIO")
                finally:
                    await exporter.close()

            print(f"{'='*60}\n")

        except Exception as e:
            print(f"❌ Error re-analyzing: {e}")
            import traceback
            traceback.print_exc()
    
    asyncio.create_task(reanalyze_background())
    
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
