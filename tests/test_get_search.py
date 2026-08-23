import asyncio
import os
import unittest
from datetime import datetime, timedelta
from unittest.mock import AsyncMock

os.environ.setdefault("TMDB_API_KEY", "test")
os.environ.setdefault("DATABASE_URL", "postgresql://u:p@localhost/db")

from src.get_search import (
    GET_SEARCH_TTL,
    _get_search_cache,
    get_search_cache_key,
    get_search_list,
    reset_get_search_state,
)

IMAGE_BASE = "https://image.tmdb.org/t/p/w500"

TMDB_HIT = [
    {
        "id": 27205,
        "title": "Inception",
        "release_date": "2010-07-16",
        "poster_path": "/inception.jpg",
        "overview": "A thief who steals dreams.",
    }
]


class GetSearchKeyTests(unittest.TestCase):
    def test_key_is_casefold_plus_year(self):
        self.assertEqual(
            get_search_cache_key("Inception", 2010),
            get_search_cache_key("INCEPTION", 2010),
        )
        self.assertNotEqual(
            get_search_cache_key("Inception", 2010),
            get_search_cache_key("Inception", 2011),
        )
        self.assertEqual(get_search_cache_key("Foo", None), "foo|None")


class GetSearchBehaviorTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        reset_get_search_state()
        self.tmdb = AsyncMock(return_value=TMDB_HIT)
        self.db = AsyncMock(return_value=[])

    async def _search(self, query="Inception", year=None):
        return await get_search_list(
            query, year, self.tmdb, self.db, IMAGE_BASE
        )

    async def test_response_shape(self):
        payload = await self._search("Inception", 2010)
        self.assertEqual(payload["query"], "Inception")
        self.assertEqual(payload["count"], 1)
        row = payload["results"][0]
        self.assertEqual(
            set(row), {"id", "title", "year", "posterPath", "overview"}
        )
        self.assertEqual(row["id"], 27205)
        self.assertEqual(row["title"], "Inception")
        self.assertEqual(row["year"], 2010)
        self.assertEqual(row["posterPath"], IMAGE_BASE + "/inception.jpg")
        self.assertEqual(row["overview"], "A thief who steals dreams.")

    async def test_ttl_cache_avoids_second_tmdb_call(self):
        await self._search("Inception", None)
        await self._search("inception", None)
        self.assertEqual(self.tmdb.await_count, 1)
        self.assertGreaterEqual(GET_SEARCH_TTL, timedelta(minutes=10))

    async def test_expired_cache_refetches(self):
        await self._search("Inception", None)
        key = get_search_cache_key("Inception", None)
        payload = _get_search_cache[key][1]
        _get_search_cache[key] = (
            datetime.now() - timedelta(seconds=1),
            payload,
        )
        await self._search("Inception", None)
        self.assertEqual(self.tmdb.await_count, 2)

    async def test_single_flight_shares_one_tmdb_call(self):
        started = asyncio.Event()
        release = asyncio.Event()
        calls = {"n": 0}

        async def slow_tmdb(query, year=None, limit=20):
            calls["n"] += 1
            started.set()
            await release.wait()
            return TMDB_HIT

        first = asyncio.create_task(
            get_search_list("Inception", None, slow_tmdb, self.db, IMAGE_BASE)
        )
        await started.wait()
        second = asyncio.create_task(
            get_search_list("Inception", None, slow_tmdb, self.db, IMAGE_BASE)
        )
        await asyncio.sleep(0)
        release.set()
        a, b = await asyncio.gather(first, second)
        self.assertEqual(calls["n"], 1)
        self.assertEqual(a, b)

    async def test_tmdb_failure_falls_back_to_postgres(self):
        self.tmdb.side_effect = RuntimeError("tmdb down")
        self.db.return_value = [
            {
                "id": 99,
                "title": "Inception",
                "year": 2010,
                "poster_path": "https://image.tmdb.org/t/p/w500/x.jpg",
                "overview": "local",
            }
        ]
        payload = await self._search("Inception", 2010)
        self.db.assert_awaited()
        self.assertEqual(payload["count"], 1)
        self.assertEqual(payload["results"][0]["id"], 99)
        self.assertEqual(payload["results"][0]["overview"], "local")

    async def test_does_not_enqueue_or_scrape(self):
        await self._search()
        with open("src/get_search.py", encoding="utf-8") as fh:
            helper = fh.read()
        with open("src/api.py", encoding="utf-8") as fh:
            api = fh.read()
        self.assertNotIn("enqueue_extract_job", helper)
        self.assertNotIn("MovieInsights", helper)
        get_block = api.split("async def search_movies_get", 1)[1]
        get_block = get_block.split("async def search_movie", 1)[0]
        self.assertNotIn("enqueue_extract_job", get_block)
        self.assertIn("search_movies_ilike", get_block)
        self.assertIn("ILIKE", open("src/database.py", encoding="utf-8").read())

    async def test_empty_query_skips_tmdb(self):
        payload = await self._search("  ", None)
        self.assertEqual(payload["count"], 0)
        self.tmdb.assert_not_called()
        self.db.assert_not_called()

    async def test_year_is_forwarded_to_tmdb(self):
        await self._search("It", 2017)
        self.tmdb.assert_awaited()
        self.assertEqual(self.tmdb.await_args.args[0], "It")
        self.assertEqual(self.tmdb.await_args.args[1], 2017)

    async def test_short_titles_keep_tmdb_order(self):
        """Typeahead must not re-rank short catalog titles over TMDB."""
        cases = [
            (
                "Sh",
                [
                    {"id": 1484775, "title": "Sh", "release_date": "2025-01-01", "poster_path": "/sh.jpg", "overview": "short"},
                    {"id": 37165, "title": "The Truman Show", "release_date": "1998-06-05", "poster_path": "/t.jpg", "overview": "truman"},
                ],
                "Sh",
            ),
            (
                "It",
                [
                    {"id": 346364, "title": "It", "release_date": "2017-09-08", "poster_path": "/it.jpg", "overview": "clown"},
                    {"id": 62, "title": "2001: A Space Odyssey", "release_date": "1968-04-02", "poster_path": "/o.jpg", "overview": "odyssey"},
                ],
                "It",
            ),
            (
                "Up",
                [
                    {"id": 14160, "title": "Up", "release_date": "2009-05-29", "poster_path": "/up.jpg", "overview": "balloons"},
                ],
                "Up",
            ),
            (
                "Her",
                [
                    {"id": 152601, "title": "Her", "release_date": "2013-12-18", "poster_path": "/her.jpg", "overview": "os"},
                ],
                "Her",
            ),
            (
                "Truman show",
                [
                    {"id": 37165, "title": "The Truman Show", "release_date": "1998-06-05", "poster_path": "/t.jpg", "overview": "truman"},
                    {"id": 1484775, "title": "Sh", "release_date": "2025-01-01", "poster_path": "/sh.jpg", "overview": "short"},
                ],
                "The Truman Show",
            ),
        ]
        for query, hits, first in cases:
            self.tmdb.reset_mock()
            self.tmdb.return_value = hits
            self.tmdb.side_effect = None
            payload = await self._search(query, None)
            self.assertEqual(payload["results"][0]["title"], first, query)
            self.assertEqual(
                [row["title"] for row in payload["results"]],
                [h["title"] for h in hits],
                query,
            )

    async def test_postgres_fallback_is_title_contains_query(self):
        """ILIKE '%truman show%' must not invent a reverse includes() hit."""
        self.tmdb.side_effect = RuntimeError("tmdb down")
        self.db.return_value = []
        payload = await self._search("Truman show", None)
        self.db.assert_awaited()
        self.assertEqual(self.db.await_args.args[0], "Truman show")
        self.assertEqual(payload["count"], 0)
        self.assertEqual(payload["results"], [])


class GetSearchContractTests(unittest.TestCase):
    def test_ilike_is_not_bidirectional(self):
        with open("src/database.py", encoding="utf-8") as fh:
            src = fh.read()
        self.assertIn('pattern = f"%{query}%"', src)
        self.assertIn("title ILIKE $1", src)
        self.assertNotIn("query ILIKE", src)

    def test_get_search_accepts_q_alias(self):
        with open("src/api.py", encoding="utf-8") as fh:
            src = fh.read()
        self.assertIn('q: str = ""', src)
        self.assertIn("query or q", src)
        self.assertIn("movie_id: Optional[int] = None", src)

if __name__ == "__main__":
    unittest.main()
