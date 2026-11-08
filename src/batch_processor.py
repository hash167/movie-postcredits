"""
Batch processor for collecting movie and post-credits data
"""

import asyncio
from typing import Dict
from src.tmdb_client import TMDBClient
from src.movie_insights import MovieInsights
from src.database import DatabaseManager
from src.models import EnhancedMovie


class BatchProcessor:
    """Process movies in batches and collect post-credits information"""

    def __init__(self):
        self.tmdb = TMDBClient()
        self.insights = MovieInsights()
        self.db = DatabaseManager()

    async def initialize(self):
        """Initialize database connection"""
        await self.db.connect()

    async def close(self):
        """Close database connection"""
        await self.db.close()

    async def process_tier(self, tier: str):
        """Process movies for a specific tier"""
        print(f"\n{'='*60}")
        print(f"Processing tier: {tier}")
        print(f"{'='*60}\n")

        # Log batch start
        batch_id = await self.db.log_batch_start(tier)

        # Fetch movies based on tier
        if tier == "theaters":
            all_movies = await self.tmdb.get_movies_in_theaters(limit=50)
            # Filter to only include movies from current or previous year
            from datetime import datetime
            current_year = datetime.now().year
            
            # Extract year from release_date before filtering
            movies = []
            for m in all_movies:
                release_date = m.get('release_date', '')
                if release_date and len(release_date) >= 4:
                    try:
                        movie_year = int(release_date[:4])
                        if movie_year >= current_year - 1:
                            movies.append(m)
                    except ValueError:
                        # If year parsing fails, include the movie anyway
                        movies.append(m)
                else:
                    # If no release date, include it anyway (let processing decide)
                    movies.append(m)
            
            print(f"Filtered {len(all_movies)} down to {len(movies)} recent theater movies")
        elif tier == "popular":
            movies = await self.tmdb.get_popular_movies(limit=1000)
        elif tier == "recent":
            movies = await self.tmdb.get_recent_releases(years=2)
        else:
            print(f"Unknown tier: {tier}")
            return

        print(f"Found {len(movies)} movies for tier '{tier}'")

        processed = 0
        failed = 0

        # Process movies with rate limiting
        for i, movie_data in enumerate(movies, 1):
            try:
                title = movie_data.get("title")
                print(f"[{i}/{len(movies)}] Processing: {title}")
                await self.process_movie(movie_data, tier)
                processed += 1

                # Rate limiting to be nice to APIs
                if i % 10 == 0:
                    print(f"  Processed {i} movies, pausing...")
                    await asyncio.sleep(2)

            except Exception as e:
                print(f"  ERROR processing {movie_data.get('title')}: {e}")
                failed += 1
                continue

        # After theaters scrape: demote titles no longer in TMDB now_playing
        # so export/UI stop listing historical theater rows forever.
        if tier == "theaters":
            keep_ids = [m.get("id") for m in movies if m.get("id") is not None]
            demoted = await self.db.demote_stale_theater_movies(keep_ids)
            print(
                f"Demoted {demoted} stale theater movie(s); "
                f"keeping {len(keep_ids)} current now_playing id(s)"
            )

        # Log batch completion
        await self.db.log_batch_complete(batch_id, processed, failed)

        print(f"\n{'='*60}")
        print(f"Tier '{tier}' completed:")
        print(f"  Processed: {processed}")
        print(f"  Failed: {failed}")
        print(f"{'='*60}\n")

    async def process_movie(self, movie_data: Dict, tier: str):
        """Process a single movie"""
        movie_id = movie_data["id"]
        title = movie_data.get("title", "Unknown")

        # Get detailed movie information
        details = await self.tmdb.get_movie_details(movie_id)
        if not details:
            print(f"  Could not fetch details for {title}")
            return

        # Format movie data
        formatted = self.tmdb.format_movie(details, tier)

        # Search live articles and IMDb for insights
        year = formatted.get("year")
        imdb_id = formatted.get("imdb_id")
        insights = await self.insights.scrape_movie_insights(
            title,
            year,
            imdb_id,
            movie_id=movie_id,
            overview=formatted.get("overview") or details.get("overview") or "",
        )

        # Create EnhancedMovie object
        enhanced_movie = EnhancedMovie(**formatted, movie_insights=insights)

        # Save to database
        await self.db.upsert_movie(enhanced_movie)

        if insights:
            has_scene = insights.post_credits.has_scene
            egg_count = len(insights.easter_eggs)
            msg = f"Post-credits={has_scene}, Easter eggs={egg_count}"
            print(f"  ✓ Saved: {msg}")
        else:
            print("  ✓ Saved (no insights)")

    async def process_specific_movie(self, title: str, year: int = None):
        """Process a specific movie by title"""
        print(f"Searching for movie: {title}")

        movie_data = await self.tmdb.search_movie(title, year)

        if not movie_data:
            print(f"Movie not found: {title}")
            return

        title_str = movie_data["title"]
        date_str = movie_data.get("release_date", "Unknown")[:4]
        print(f"Found: {title_str} ({date_str})")

        # Determine tier (default to 'on-demand')
        tier = "on-demand"

        await self.process_movie(movie_data, tier)
        print(f"✓ Completed processing: {title}")

    async def process_all_tiers(self):
        """Process all tiers in sequence"""
        tiers = ["theaters", "popular", "recent"]

        for tier in tiers:
            await self.process_tier(tier)

    async def update_existing_movies(self, tier: str = None):
        """Update existing movies in the database with fresh data"""
        print("Updating existing movies...")

        if tier:
            movies = await self.db.get_movies_by_tier(tier)
        else:
            # Get all movies
            async with self.db.pool.acquire() as conn:
                query = "SELECT id, title, year, tier FROM movies"
                rows = await conn.fetch(query)
                movies = [dict(row) for row in rows]

        print(f"Found {len(movies)} movies to update")

        for i, movie in enumerate(movies, 1):
            try:
                print(f"[{i}/{len(movies)}] Updating: {movie['title']}")

                # Get fresh data from TMDB
                details = await self.tmdb.get_movie_details(movie["id"])
                if details:
                    # Scrape live articles for new insights
                    insights = await self.insights.scrape_movie_insights(
                        movie["title"], movie.get("year")
                    )

                    # Format and save
                    tier_val = movie.get("tier", "on-demand")
                    formatted = self.tmdb.format_movie(details, tier_val)
                    enhanced_movie = EnhancedMovie(
                        **formatted, movie_insights=insights
                    )
                    await self.db.upsert_movie(enhanced_movie)

                    print("  ✓ Updated")

                # Rate limiting
                if i % 10 == 0:
                    await asyncio.sleep(2)

            except Exception as e:
                print(f"  ERROR: {e}")
                continue

        print("Update completed!")
