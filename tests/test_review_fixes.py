"""Regression tests for the first AgentFlow review of f678187."""
import asyncio
import os
import socket

import pytest

from src.movie_insights import _is_public_http_url, _usable_url

TEST_DSN = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql://moviesync:test-only-db@127.0.0.1:5432/moviesync",
)


def test_catalog_proxy_has_no_variable_and_limit_uses_peer():
    text = open("frontend/nginx.conf", encoding="utf-8").read()
    assert "CF-Connecting-IP" not in text.split("limit_req_zone", 1)[1].split(";", 1)[0]
    assert "limit_req_zone $binary_remote_addr" in text
    catalog = text.split("location ~ ^/(theaters|popular|recent|on-demand)-movies", 1)[1]
    proxy = [line.strip() for line in catalog.splitlines() if "proxy_pass" in line][0]
    assert "$" not in proxy
    assert "minio.movie-api.svc.cluster.local:9000" in proxy
    assert "rewrite ^ /movies/$1-movies.json break;" in text


def test_private_and_link_local_urls_are_not_fetchable():
    assert _usable_url("http://169.254.169.254/latest/meta-data") == ""
    assert _usable_url("http://127.0.0.1/") == ""
    assert _usable_url("http://10.1.2.3/admin") == ""
    assert _usable_url("http://192.168.1.1/") == ""
    assert _usable_url("file:///etc/passwd") == ""
    assert _usable_url("http://user:pass@8.8.8.8/x") == ""
    assert _is_public_http_url("http://8.8.8.8/article") is True


def test_hostname_resolving_private_is_rejected(monkeypatch):
    def fake_getaddrinfo(host, port, *args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("169.254.169.254", 0))]

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)
    assert _usable_url("http://metadata.example.test/latest") == ""


def test_redirect_to_link_local_is_not_fetched():
    import httpx
    from src.movie_insights import MovieInsights

    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.host)
        if request.url.path == "/go":
            return httpx.Response(
                302, headers={"location": "http://169.254.169.254/latest/meta-data"}
            )
        raise AssertionError(f"unexpected request {request.url}")

    async def run():
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport, follow_redirects=False) as client:
            insights = MovieInsights()
            return await insights._get_public(client, "http://8.8.8.8/go")

    assert asyncio.run(run()) is None
    assert seen == ["8.8.8.8"]


def test_search_cache_drops_expired_and_caps(monkeypatch):
    import src.api as api

    api._search_mem.clear()
    api._search_inflight.clear()
    now = 1_000.0
    api._search_mem["old"] = (now - 1, {"query": "old"})
    api._search_mem["keep"] = (now + 50, {"query": "keep"})
    api._purge_search_cache(now)
    assert "old" not in api._search_mem
    assert "keep" in api._search_mem

    monkeypatch.setattr(api, "_SEARCH_MAX", 2)
    api._search_mem.clear()
    api._search_mem["a"] = (now + 1, {})
    api._search_mem["b"] = (now + 2, {})
    api._search_mem["c"] = (now + 3, {})
    api._purge_search_cache(now)
    assert set(api._search_mem) == {"b", "c"}


def test_worth_staying_bool_and_empty_eggs_and_job_fence():
    if "127.0.0.1" not in TEST_DSN and "localhost" not in TEST_DSN:
        pytest.skip("refusing non-local database")
    pytest.importorskip("asyncpg")
    import asyncpg
    from src import config
    from src.database import DatabaseManager
    from src.models import EasterEgg, EnhancedMovie, MovieInsightsData, PostCreditsScene
    from tests.test_schema_startup import _reset

    async def run():
        conn = await asyncpg.connect(TEST_DSN)
        try:
            await _reset(conn)
        finally:
            await conn.close()
        config.settings.database_url = TEST_DSN
        db = DatabaseManager()
        await db.connect()
        try:
            movie = EnhancedMovie(
                id=1,
                title="Example",
                year=2026,
                tier="on-demand",
                movie_insights=MovieInsightsData(
                    easter_eggs=[
                        EasterEgg(detail="A hidden poster", significance="sig", confidence="high")
                    ],
                    post_credits=PostCreditsScene(
                        has_scene=True,
                        scene_count=1,
                        descriptions=["mid", "post"],
                        worth_staying=False,
                        spoiler_free_hint=None,
                    ),
                    discussion_count=0,
                    source_urls=[],
                ),
            )
            await db.upsert_movie(movie)
            check = await asyncpg.connect(TEST_DSN)
            try:
                worth = await check.fetchval(
                    "SELECT worth_staying FROM post_credits WHERE movie_id = 1"
                )
                assert worth is False
                movie.movie_insights.easter_eggs = []
                movie.movie_insights.post_credits.worth_staying = True
                await db.upsert_movie(movie)
                eggs = await check.fetchval(
                    "SELECT COUNT(*) FROM easter_eggs WHERE movie_id = 1"
                )
                worth = await check.fetchval(
                    "SELECT worth_staying FROM post_credits WHERE movie_id = 1"
                )
                assert eggs == 0
                assert worth is True

                await check.execute(
                    """
                    INSERT INTO extract_jobs (movie_id, title, year, status, attempts)
                    VALUES (1, 'Example', 2026, 'queued', 0)
                    """
                )
            finally:
                await check.close()
            first = await db.claim_next_job()
            assert first["attempts"] == 1
            await db.pool.execute(
                """
                UPDATE extract_jobs
                SET started_at = NOW() - INTERVAL '11 minutes'
                WHERE id = $1
                """,
                first["id"],
            )
            reclaimed = await db.reclaim_stale_jobs()
            assert reclaimed["requeued"] == 1
            second = await db.claim_next_job()
            assert second["attempts"] == 2
            await db.mark_job_done(first["id"], first["attempts"])
            status = await db.pool.fetchval(
                "SELECT status FROM extract_jobs WHERE id = $1", first["id"]
            )
            attempts = await db.pool.fetchval(
                "SELECT attempts FROM extract_jobs WHERE id = $1", first["id"]
            )
            assert status == "running"
            assert attempts == 2
            await db.mark_job_done(second["id"], second["attempts"])
            status = await db.pool.fetchval(
                "SELECT status FROM extract_jobs WHERE id = $1", second["id"]
            )
            assert status == "done"
        finally:
            await db.close()

    asyncio.run(run())
