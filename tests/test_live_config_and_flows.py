"""Env overrides and mocked search/batch. No network and no real credentials."""
import asyncio

import pytest

from src.config import Settings
from src.movie_insights import MovieInsights


def test_settings_use_env_not_empty_defaults(monkeypatch):
    monkeypatch.setenv("TMDB_API_KEY", "test-only-not-a-real-key")
    monkeypatch.setenv("DATABASE_URL", "postgresql://movieuser@127.0.0.1:5432/moviesync")
    monkeypatch.setenv("S3_ENDPOINT", "http://minio.example.test:9000")
    monkeypatch.setenv("S3_ACCESS_KEY", "test-access")
    monkeypatch.setenv("S3_SECRET_KEY", "test-secret")
    monkeypatch.setenv("OLLAMA_HOST", "http://ollama.example.test:11434")
    settings = Settings()
    assert settings.s3_endpoint == "http://minio.example.test:9000"
    assert settings.s3_access_key == "test-access"
    assert settings.s3_secret_key == "test-secret"
    assert settings.ollama_host == "http://ollama.example.test:11434"
    assert settings.tmdb_api_key == "test-only-not-a-real-key"
    assert "REDACTED" not in settings.s3_endpoint


def test_movie_insights_reads_ollama_host(monkeypatch):
    monkeypatch.setenv("OLLAMA_HOST", "http://ollama.example.test:11434")
    monkeypatch.setenv("OLLAMA_MODEL", "llama3.1:8b")
    client = MovieInsights()
    assert client.ollama_host == "http://ollama.example.test:11434"


def test_empty_ollama_host_does_not_call_http(monkeypatch):
    monkeypatch.setenv("OLLAMA_HOST", "")
    client = MovieInsights()

    def boom(*args, **kwargs):
        raise AssertionError("httpx should not be called")

    monkeypatch.setattr("httpx.AsyncClient", boom)
    with pytest.raises(RuntimeError, match="OLLAMA_HOST"):
        asyncio.run(client.eggs_from_ollama("Example", 2026, [("http://example.test/a", "text")]))


def test_search_accepts_q_without_tmdb_network(monkeypatch):
    import src.api as api

    async def fake_search(query, year):
        assert query == "Spy"
        assert year is None
        return [{"id": 7, "title": "Spy", "year": 1999, "poster_path": None, "overview": "ok"}]

    monkeypatch.setattr(api.tmdb, "search_movies", fake_search)
    api._search_mem.clear()
    api._search_inflight.clear()
    result = asyncio.run(api.search_movies_list(q="Spy", query=""))
    assert result["query"] == "Spy"
    assert result["count"] == 1
    assert result["results"][0]["title"] == "Spy"


def test_search_falls_back_to_local_when_tmdb_raises(monkeypatch):
    import src.api as api

    async def fake_search(query, year):
        raise RuntimeError("tmdb down")

    async def fake_local(query, year=None):
        return [{"id": 8, "title": query, "year": None, "posterPath": None, "overview": "local"}]

    monkeypatch.setattr(api.tmdb, "search_movies", fake_search)
    monkeypatch.setattr(api, "_local_movie_hits", fake_local)
    api._search_mem.clear()
    api._search_inflight.clear()
    result = asyncio.run(api.search_movies_list(query="Local Only"))
    assert result["results"][0]["overview"] == "local"
    assert result["count"] == 1


def test_empty_now_playing_reaches_demote_as_empty_list(monkeypatch):
    from src.batch_processor import BatchProcessor

    class TMDB:
        async def get_movies_in_theaters(self, limit=50):
            return []

    class DB:
        def __init__(self):
            self.keep_ids = "unset"

        async def log_batch_start(self, tier):
            return 1

        async def log_batch_complete(self, batch_id, processed, failed):
            return None

        async def demote_stale_theater_movies(self, keep_ids):
            self.keep_ids = list(keep_ids)
            return 0

    processor = BatchProcessor.__new__(BatchProcessor)
    processor.tmdb = TMDB()
    processor.db = DB()
    processor.insights = None
    asyncio.run(processor.process_tier("theaters"))
    assert processor.db.keep_ids == []


def test_theater_batch_does_not_call_ollama(monkeypatch):
    from src.batch_processor import BatchProcessor

    class TMDB:
        async def get_movies_in_theaters(self, limit=50):
            return [{"id": 42, "title": "Example", "release_date": "2026-01-01"}]

    class DB:
        def __init__(self):
            self.keep_ids = None

        async def log_batch_start(self, tier):
            return 1

        async def log_batch_complete(self, batch_id, processed, failed):
            return None

        async def demote_stale_theater_movies(self, keep_ids):
            self.keep_ids = list(keep_ids)
            return 0

    called = []

    async def process_movie(self, movie_data, tier):
        called.append(movie_data["id"])

    processor = BatchProcessor.__new__(BatchProcessor)
    processor.tmdb = TMDB()
    processor.db = DB()
    processor.insights = None
    processor.process_movie = process_movie.__get__(processor, BatchProcessor)
    asyncio.run(processor.process_tier("theaters"))
    assert called == [42]
    assert processor.db.keep_ids == [42]
