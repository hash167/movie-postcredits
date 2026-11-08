"""Shared extract helper used by the API enqueue path and extract_worker."""

from src.models import EnhancedMovie


def year_from(movie_data, fallback=None):
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


def poster_url(movie_data, image_base):
    poster = movie_data.get("poster_path") or movie_data.get("posterPath")
    if not poster:
        return None
    if str(poster).startswith("http"):
        return poster
    return f"{image_base}{poster}"


async def fill_insights(db, tmdb, extractor, movie_id, movie_data, year, poster, tier="on-demand"):
    """Run MovieInsights (TMDB keywords + live articles + Ollama) and upsert."""
    print(f"\n{'='*60}")
    print(f"Insights pipeline: {movie_data.get('title')} (ID: {movie_id})")
    print(f"{'='*60}")

    full_movie = movie_data
    if not full_movie.get("imdb_id") or full_movie.get("runtime") is None:
        try:
            fetched = await tmdb.get_movie_details(movie_id)
            if fetched:
                full_movie = fetched
        except Exception as e:
            print(f"TMDB details fallback failed: {e}")

    year = year_from(full_movie, year)
    poster = poster_url(full_movie, tmdb.image_base) or poster

    movie_obj = EnhancedMovie(
        id=full_movie["id"],
        title=full_movie["title"],
        year=year,
        release_date=full_movie.get("release_date"),
        runtime_minutes=full_movie.get("runtime") or full_movie.get("runtime_minutes") or 0,
        poster_path=poster,
        overview=full_movie.get("overview", ""),
        vote_average=full_movie.get("vote_average", 0.0),
        popularity=full_movie.get("popularity", 0.0),
        imdb_id=full_movie.get("imdb_id"),
        tier=tier,
    )

    print(f"Live articles + Ollama for: {movie_obj.title} {movie_obj.year} id={movie_id}")
    insights = await extractor.scrape_movie_insights(
        movie_obj.title,
        movie_obj.year,
        movie_obj.imdb_id,
        movie_id=movie_id,
        overview=movie_obj.overview or "",
    )

    if insights:
        print(f"✓ Easter eggs: {len(insights.easter_eggs)}")
        print(f"✓ Post-credits: {insights.post_credits.has_scene}")
        movie_obj.movie_insights = insights
    else:
        print("⚠ No insights returned")

    await db.upsert_movie(movie_obj)
    print("✓ Saved to database")

    has_content = False
    if insights:
        has_content = insights.post_credits.has_scene or len(insights.easter_eggs) > 0
    if has_content:
        try:
            print("📤 Exporting to MinIO (has content)...")
            from src.json_exporter import JSONExporter
            from src.storage_uploader import StorageUploader

            exporter = JSONExporter()
            uploader = StorageUploader()
            await exporter.initialize()
            try:
                filepath = await exporter.export_tier(movie_obj.tier or "on-demand")
                await uploader.upload_file(filepath)
                print("✓ Exported and uploaded to MinIO")
            finally:
                await exporter.close()
        except Exception as e:
            print(f"Export skipped: {e}")

    print(f"{'='*60}\n")
    return await db.get_movie_by_id(movie_id)
