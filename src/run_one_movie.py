#!/usr/bin/env python3
"""Run MovieInsights for one TMDB id and upsert. No invented eggs."""
import asyncio
import os
import sys
import traceback

os.chdir("/app")
sys.path.insert(0, "/app")

from src.database import DatabaseManager
from src.models import EnhancedMovie
from src.movie_insights import MovieInsights
from src.tmdb_client import TMDBClient


async def main():
    movie_id = int(sys.argv[1])
    tier = sys.argv[2] if len(sys.argv) > 2 else "on-demand"
    db = DatabaseManager()
    tmdb = TMDBClient()
    extractor = MovieInsights()
    await db.connect()
    try:
        details = await tmdb.get_movie_details(movie_id)
        if not details:
            print("NO_DETAILS", movie_id, flush=True)
            return
        formatted = tmdb.format_movie(details, tier)
        print(
            "START id=%s title=%s year=%s" % (
                formatted.get("id"), formatted.get("title"), formatted.get("year")
            ),
            flush=True,
        )
        insights = await extractor.scrape_movie_insights(
            formatted["title"],
            formatted.get("year"),
            formatted.get("imdb_id"),
            movie_id=movie_id,
            overview=formatted.get("overview") or "",
        )
        movie = EnhancedMovie(**formatted, movie_insights=insights)
        await db.upsert_movie(movie)
        eggs = insights.easter_eggs if insights else []
        pc = insights.post_credits if insights else None
        print("EGGS_COUNT=%s" % len(eggs), flush=True)
        print("HAS_SCENE=%s SCENE_COUNT=%s" % (
            getattr(pc, "has_scene", None), getattr(pc, "scene_count", None)
        ), flush=True)
        for e in eggs[:8]:
            detail = (getattr(e, "detail", None) or "")[:160].replace("\n", " ")
            sig = (getattr(e, "significance", None) or "")[:50]
            print("EGG=%s | %s" % (detail, sig), flush=True)
        print("UPSERT_OK", flush=True)
    except Exception:
        traceback.print_exc()
        raise
    finally:
        await db.close()


if __name__ == "__main__":
    asyncio.run(main())
