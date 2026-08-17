import os
import unittest
from unittest.mock import AsyncMock, patch

os.environ.setdefault("TMDB_API_KEY", "test")
os.environ.setdefault("DATABASE_URL", "postgresql://u:p@localhost/db")

from src.web_search import (
    decode_ddg_url,
    html_to_text,
    parse_ddg_result_urls,
    search_queries,
)


class WebSearchParseTests(unittest.TestCase):
    def test_search_queries_include_eggs_and_credits(self):
        queries = search_queries("The Odyssey", 2026)
        self.assertEqual(queries[0], "The Odyssey 2026 easter eggs")
        self.assertEqual(queries[1], "The Odyssey 2026 post-credits scene")

    def test_decode_ddg_uddg_and_skip_blocked_hosts(self):
        encoded = (
            "https://duckduckgo.com/l/?uddg="
            "https%3A%2F%2Fvariety.com%2F2026%2Feggs%2F"
        )
        self.assertEqual(
            decode_ddg_url(encoded), "https://variety.com/2026/eggs/"
        )
        self.assertIsNone(decode_ddg_url("https://www.reddit.com/r/movies"))
        self.assertIsNone(decode_ddg_url("https://www.youtube.com/watch?v=1"))

    def test_parse_ddg_result_anchors(self):
        html = """
        <html><body>
          <a class="result__a" href="https://screenrant.com/odyssey-easter-eggs/">One</a>
          <a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fcollider.com%2Fpost-credits%2F">Two</a>
          <a class="result__a" href="https://duckduckgo.com/about">skip</a>
        </body></html>
        """
        urls = parse_ddg_result_urls(html, limit=5)
        self.assertEqual(
            urls,
            [
                "https://screenrant.com/odyssey-easter-eggs/",
                "https://collider.com/post-credits/",
            ],
        )

    def test_empty_result_a_hrefs_run_fallback(self):
        """Live DDG: result__a hrefs are empty, so fallback must run."""
        html = """
        <html><body>
          <a class="result__a" href=""></a>
          <a class="result__a" href=""></a>
          <a class="result__a" href=""></a>
          <a href="/l/?uddg=https%3A%2F%2Fwww.slashfilm.com%2Fevil-dead-burn-easter-eggs%2F">Slashfilm</a>
          <a href="https://screenrant.com/evil-dead-burn-ending-explained/">ScreenRant</a>
        </body></html>
        """
        urls = parse_ddg_result_urls(html, limit=5)
        self.assertIn(
            "https://www.slashfilm.com/evil-dead-burn-easter-eggs/", urls
        )
        self.assertIn(
            "https://screenrant.com/evil-dead-burn-ending-explained/", urls
        )
        self.assertGreaterEqual(len(urls), 2)

    def test_html_to_text_strips_chrome(self):
        text = html_to_text(
            "<html><script>alert(1)</script><p>Cameo after the logo.</p></html>"
        )
        self.assertIn("Cameo after the logo.", text)
        self.assertNotIn("alert", text)


class GatherCorpusTests(unittest.IsolatedAsyncioTestCase):
    async def test_gather_caps_and_skips_failures(self):
        from src import web_search

        async def fake_search(query, limit=5):
            return [
                "https://example.com/a",
                "https://example.com/b",
                "https://example.com/fail",
            ]

        async def fake_fetch(url):
            if url.endswith("/fail"):
                return ""
            return ("The post-credits scene teases a sequel. " * 20)

        with patch.object(web_search, "search_duckduckgo", fake_search), patch.object(
            web_search, "fetch_article_text", fake_fetch
        ):
            corpus = await web_search.gather_article_corpus("The Odyssey", 2026)
        self.assertGreaterEqual(len(corpus["urls"]), 1)
        self.assertIn("SOURCE:", corpus["text"])
        self.assertLessEqual(len(corpus["text"]), web_search.MAX_TOTAL_CHARS + 200)
        self.assertNotIn("https://example.com/fail", corpus["urls"])
