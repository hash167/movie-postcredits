import os
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("OPENAI_API_KEY", "test")
os.environ.setdefault("TMDB_API_KEY", "test")
os.environ.setdefault("DATABASE_URL", "postgresql://u:p@localhost/db")

from src.imdb_scraper import IMDbScraper
from src.reddit_scraper import RedditScraper


class FakeResponse:
    def __init__(self, status_code, text=""):
        self.status_code = status_code
        self.text = text


class FakeAsyncClient:
    def __init__(self, response):
        self._response = response

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def get(self, url, headers=None, follow_redirects=None):
        return self._response


class IMDbScraperTests(unittest.IsolatedAsyncioTestCase):
    def test_browser_headers_present(self):
        scraper = IMDbScraper()
        ua = scraper.headers["User-Agent"]
        self.assertIn("Mozilla/5.0", ua)
        self.assertIn("Chrome/", ua)
        self.assertIn("Accept", scraper.headers)
        self.assertIn("Accept-Language", scraper.headers)
        self.assertEqual(scraper.headers["Referer"], "https://www.imdb.com/")

    async def test_http_202_is_waf_block_and_skips_html(self):
        scraper = IMDbScraper()
        challenge = "<html><head><title></title></head><body>akamai</body></html>"
        fake = FakeAsyncClient(FakeResponse(202, challenge))
        with patch("src.imdb_scraper.httpx.AsyncClient", return_value=fake):
            with patch("builtins.print") as mock_print:
                items = await scraper._get_trivia("tt1234567")
        self.assertEqual(items, [])
        printed = " ".join(
            str(call.args[0]) for call in mock_print.call_args_list
        )
        self.assertIn("WAF", printed)
        self.assertIn("202", printed)

    async def test_non_200_does_not_parse_html(self):
        scraper = IMDbScraper()
        html = '<div class="ipc-html-content-inner-div">' + ("x" * 40) + "</div>"
        fake = FakeAsyncClient(FakeResponse(403, html))
        with patch("src.imdb_scraper.httpx.AsyncClient", return_value=fake):
            items = await scraper._get_goofs("tt1234567")
        self.assertEqual(items, [])


class PublishedKnowledgeFallbackTests(unittest.IsolatedAsyncioTestCase):
    async def test_empty_reddit_and_imdb_calls_fallback(self):
        scraper = RedditScraper()
        scraper.search_reddit = AsyncMock(return_value=[])
        scraper.imdb_scraper.get_trivia_and_goofs = AsyncMock(
            return_value={"trivia": [], "goofs": [], "total_items": 0}
        )
        fallback = AsyncMock(return_value="FALLBACK")
        scraper.analyze_published_knowledge = fallback
        scraper.analyze_with_gpt = AsyncMock(return_value="SHOULD_NOT_RUN")

        result = await scraper.scrape_movie_insights(
            "Spider-Man: Brand New Day", 2026, "tt123"
        )
        self.assertEqual(result, "FALLBACK")
        fallback.assert_awaited_once()
        scraper.analyze_with_gpt.assert_not_awaited()

    async def test_published_knowledge_never_invents_on_error(self):
        scraper = RedditScraper()
        scraper.client = MagicMock()
        scraper.client.chat.completions.create = AsyncMock(
            side_effect=RuntimeError("nope")
        )
        result = await scraper.analyze_published_knowledge("The Odyssey", 2026)
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
