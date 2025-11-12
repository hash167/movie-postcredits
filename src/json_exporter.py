"""
JSON exporter for movie and post-credits data by tier
"""

import json
import os
from datetime import datetime
from typing import List, Dict
from src.database import DatabaseManager
from src.config import settings


class JSONExporter:
    """Export movie and post-credits data to JSON by tier"""

    def __init__(self):
        self.export_dir = settings.export_dir
        os.makedirs(self.export_dir, exist_ok=True)
        self.db = DatabaseManager()

    async def initialize(self):
        """Initialize database connection"""
        await self.db.connect()

    async def close(self):
        """Close database connection"""
        await self.db.close()

    def _format_movie_for_export(self, movie: Dict) -> Dict:
        """Format a movie record for JSON export"""
        vote_avg = movie.get("vote_average")
        pop = movie.get("popularity")

        post_credits = None
        if movie.get("has_scene") is not None:
            post_credits = {
                "hasScene": movie.get("has_scene", False),
                "sceneCount": movie.get("scene_count", 0),
                "midCredits": movie.get("mid_credits"),
                "postCredits": movie.get("post_credits_desc"),
                "worthStaying": movie.get("worth_staying"),
                "spoilerFreeHint": movie.get("spoiler_free_hint"),
                "confidence": movie.get("source_confidence", "medium"),
            }

        # Parse easter_eggs if it's a JSON string
        easter_eggs = movie.get("easter_eggs", [])
        if isinstance(easter_eggs, str) and easter_eggs:
            try:
                easter_eggs = json.loads(easter_eggs)
            except json.JSONDecodeError:
                easter_eggs = []

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
            "imdbId": movie.get("imdb_id"),
            "postCredits": post_credits,
            "easterEggs": easter_eggs if isinstance(easter_eggs, list) else [],
            "redditDiscussionCount": movie.get("reddit_discussion_count"),
        }

    async def export_tier(self, tier: str) -> str:
        """Export movies for a specific tier"""
        filename = f"{tier}-movies.json"
        filepath = os.path.join(self.export_dir, filename)

        print(f"Exporting tier '{tier}' to {filepath}")

        movies = await self.db.get_movies_by_tier(tier)

        export_data = {
            "tier": tier,
            "movieCount": len(movies),
            "generatedAt": datetime.now().isoformat(),
            "movies": [self._format_movie_for_export(m) for m in movies],
        }

        # Write to file
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(
                export_data,
                f,
                indent=2,
                ensure_ascii=False,
                default=str,
            )

        print(f"✓ Exported {len(movies)} movies for tier '{tier}'")
        return filepath

    async def export_all_tiers(self) -> List[str]:
        """Export all tiers"""
        tiers = ["theaters", "popular", "recent", "on-demand"]
        filepaths = []

        for tier in tiers:
            try:
                filepath = await self.export_tier(tier)
                filepaths.append(filepath)
            except Exception as e:
                msg = f"Error exporting tier '{tier}': {e}"
                print(msg)

        return filepaths

    async def export_summary(self) -> str:
        """Export a summary of all movies with post-credits scenes"""
        filename = "post-credits-summary.json"
        filepath = os.path.join(self.export_dir, filename)

        print(f"Generating summary to {filepath}")

        async with self.db.pool.acquire() as conn:
            # Get movies with post-credits scenes
            rows = await conn.fetch(
                """
                SELECT
                    m.id, m.title, m.year, m.tier,
                    pc.has_scene, pc.scene_count, pc.worth_staying
                FROM movies m
                INNER JOIN post_credits pc ON m.id = pc.movie_id
                WHERE pc.has_scene = TRUE
                ORDER BY m.tier, m.popularity DESC
            """
            )

            movies = [dict(row) for row in rows]

            # Group by tier
            by_tier = {}
            for movie in movies:
                tier = movie.get("tier", "unknown")
                if tier not in by_tier:
                    by_tier[tier] = []
                by_tier[tier].append(
                    {
                        "id": movie["id"],
                        "title": movie["title"],
                        "year": movie["year"],
                        "sceneCount": movie["scene_count"],
                        "worthStaying": movie["worth_staying"],
                    }
                )

        export_data = {
            "totalMoviesWithPostCredits": len(movies),
            "generatedAt": datetime.now().isoformat(),
            "byTier": by_tier,
        }

        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(export_data, f, indent=2, ensure_ascii=False)

        print(f"✓ Exported summary with {len(movies)} movies")
        return filepath

    async def export_movies_with_easter_eggs(self) -> str:
        """Export movies that have easter eggs"""
        filename = "easter-eggs-collection.json"
        filepath = os.path.join(self.export_dir, filename)

        print(f"Generating easter eggs collection to {filepath}")

        async with self.db.pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT DISTINCT m.id, m.title, m.year, m.tier, m.poster_path, m.popularity
                FROM movies m
                INNER JOIN easter_eggs ee ON m.id = ee.movie_id
                ORDER BY m.popularity DESC
            """
            )

            movies = []
            for row in rows:
                movie_dict = dict(row)

                # Get easter eggs for this movie
                query = (
                    "SELECT detail, significance, confidence, "
                    "source_url FROM easter_eggs WHERE movie_id = $1"
                )
                eggs = await conn.fetch(query, movie_dict["id"])

                movies.append(
                    {
                        "id": movie_dict["id"],
                        "title": movie_dict["title"],
                        "year": movie_dict["year"],
                        "tier": movie_dict["tier"],
                        "posterPath": movie_dict["poster_path"],
                        "easterEggs": [dict(egg) for egg in eggs],
                    }
                )

        export_data = {
            "totalMovies": len(movies),
            "generatedAt": datetime.now().isoformat(),
            "movies": movies,
        }

        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(export_data, f, indent=2, ensure_ascii=False)

        print(f"✓ Exported easter eggs for {len(movies)} movies")
        return filepath

    async def export_all(self) -> Dict[str, List[str]]:
        """Export everything"""
        print("\n" + "=" * 60)
        print("Exporting all data...")
        print("=" * 60 + "\n")

        results = {
            "tier_files": await self.export_all_tiers(),
            "summary_file": await self.export_summary(),
            "easter_eggs_file": await self.export_movies_with_easter_eggs(),
        }

        print("\n" + "=" * 60)
        print("Export complete!")
        print("=" * 60)

        return results
