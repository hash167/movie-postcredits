import os
import unittest
from unittest.mock import AsyncMock, patch

os.environ.setdefault("TMDB_API_KEY", "test")
os.environ.setdefault("DATABASE_URL", "postgresql://u:p@localhost/db")

from src.insights import (
    KEYWORD_MID_CREDITS,
    KEYWORD_POST_CREDITS,
    MovieInsights,
    eggs_from_model_payload,
    extract_keywords,
    parse_json_content,
    post_credits_from_keywords,
)


class KeywordParsingTests(unittest.TestCase):
    def test_extract_keywords_from_appended_payload(self):
        details = {
            "keywords": {
                "keywords": [
                    {"id": KEYWORD_POST_CREDITS, "name": "post-credits scene"},
                    {"id": 123, "name": "superhero"},
                ]
            }
        }
        kws = extract_keywords(details)
        self.assertEqual(len(kws), 2)
        self.assertEqual(kws[0]["id"], KEYWORD_POST_CREDITS)

    def test_extract_keywords_from_dedicated_endpoint_shape(self):
        details = {
            "keywords": [
                {"id": KEYWORD_MID_CREDITS, "name": "mid-credits scene"}
            ]
        }
        self.assertEqual(extract_keywords(details)[0]["id"], KEYWORD_MID_CREDITS)

    def test_post_credits_from_both_tags(self):
        scene = post_credits_from_keywords(
            [
                {"id": KEYWORD_MID_CREDITS, "name": "mid-credits scene"},
                {"id": KEYWORD_POST_CREDITS, "name": "post-credits scene"},
            ]
        )
        self.assertTrue(scene.has_scene)
        self.assertEqual(scene.scene_count, 2)
        self.assertTrue(scene.worth_staying)
        self.assertEqual(len(scene.descriptions), 2)

    def test_post_credits_from_post_only(self):
        scene = post_credits_from_keywords(
            [{"id": KEYWORD_POST_CREDITS, "name": "post-credits scene"}]
        )
        self.assertTrue(scene.has_scene)
        self.assertEqual(scene.scene_count, 1)
        self.assertIn("Post-credits", scene.descriptions[0])

    def test_no_credit_keywords_means_no_scene(self):
        scene = post_credits_from_keywords([{"id": 1, "name": "space"}])
        self.assertFalse(scene.has_scene)
        self.assertEqual(scene.scene_count, 0)
        self.assertFalse(scene.worth_staying)

    def test_tmdb_is_source_of_truth_not_ollama(self):
        scene = post_credits_from_keywords([])
        self.assertFalse(scene.has_scene)


class OllamaParseTests(unittest.TestCase):
    def test_parse_plain_json(self):
        data = parse_json_content('{"easter_eggs": []}')
        self.assertEqual(data["easter_eggs"], [])

    def test_parse_fenced_json(self):
        data = parse_json_content(
            'Sure.\n```json\n{"easter_eggs": [{"detail": "Cameo"}]}\n```'
        )
        self.assertEqual(data["easter_eggs"][0]["detail"], "Cameo")

    def test_eggs_from_payload_skips_empty(self):
        eggs = eggs_from_model_payload(
            {
                "easter_eggs": [
                    {"detail": "  ", "significance": "nope"},
                    {"detail": "Stan Lee cameo", "significance": "MCU"},
                ]
            }
        )
        self.assertEqual(len(eggs), 1)
        self.assertEqual(eggs[0].detail, "Stan Lee cameo")

    def test_eggs_from_payload_truncates_significance_to_50(self):
        eggs = eggs_from_model_payload(
            {
                "easter_eggs": [
                    {
                        "detail": "Cameo",
                        "significance": "x" * 80,
                    }
                ]
            }
        )
        self.assertEqual(len(eggs[0].significance), 50)


class MovieInsightsTests(unittest.IsolatedAsyncioTestCase):
    async def test_analyze_uses_tmdb_keywords_when_ollama_fails(self):
        analyzer = MovieInsights(
            ollama_host="http://ollama.test", ollama_model="llama3.1:8b"
        )
        analyzer.extract_easter_eggs = AsyncMock(return_value=([], []))
        details = {
            "title": "The Odyssey",
            "release_date": "2026-07-17",
            "overview": "A retelling.",
            "keywords": {
                "keywords": [
                    {"id": KEYWORD_POST_CREDITS, "name": "post-credits scene"}
                ]
            },
        }
        insights = await analyzer.analyze_movie(details)
        self.assertTrue(insights.post_credits.has_scene)
        self.assertEqual(insights.post_credits.scene_count, 1)
        self.assertEqual(insights.easter_eggs, [])
        self.assertEqual(insights.reddit_discussion_count, 0)

    async def test_no_articles_skips_ollama_and_returns_empty(self):
        analyzer = MovieInsights(
            ollama_host="http://ollama.test", ollama_model="llama3.1:8b"
        )
        analyzer._chat_json = AsyncMock()
        with patch(
            "src.insights.gather_article_corpus",
            AsyncMock(return_value={"urls": [], "text": ""}),
        ):
            eggs, urls = await analyzer.extract_easter_eggs(
                {"title": "Brand New Day", "release_date": "2026-07-31"}
            )
        self.assertEqual(eggs, [])
        self.assertEqual(urls, [])
        analyzer._chat_json.assert_not_awaited()

    async def test_ollama_extracts_only_from_article_text(self):
        analyzer = MovieInsights(
            ollama_host="http://100.67.63.33:11434",
            ollama_model="llama3.1:8b",
        )

        class FakeResponse:
            status_code = 200

            def raise_for_status(self):
                return None

            def json(self):
                return {
                    "choices": [
                        {
                            "message": {
                                "content": (
                                    '{"easter_eggs":[{"detail":'
                                    '"Mid-credits cameo from the article",'
                                    '"significance":"franchise"}]}'
                                )
                            }
                        }
                    ]
                }

        class FakeClient:
            def __init__(self):
                self.posts = []

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

            async def post(self, url, json=None):
                self.posts.append((url, json))
                return FakeResponse()

        fake = FakeClient()
        article = (
            "SOURCE: https://example.com/eggs\n"
            "The mid-credits scene shows a cameo teasing the sequel."
        )
        with patch(
            "src.insights.gather_article_corpus",
            AsyncMock(
                return_value={
                    "urls": ["https://example.com/eggs"],
                    "text": article,
                }
            ),
        ), patch("src.insights.httpx.AsyncClient", return_value=fake):
            eggs, urls = await analyzer.extract_easter_eggs(
                {
                    "title": "Spider-Man: Brand New Day",
                    "release_date": "2026-07-31",
                    "overview": "A new adventure.",
                    "keywords": {"keywords": []},
                }
            )
        self.assertEqual(len(eggs), 1)
        self.assertIn("cameo", eggs[0].detail.lower())
        self.assertEqual(urls, ["https://example.com/eggs"])
        url, body = fake.posts[0]
        self.assertEqual(
            url, "http://100.67.63.33:11434/v1/chat/completions"
        )
        self.assertEqual(body["model"], "llama3.1:8b")
        user_prompt = body["messages"][1]["content"]
        self.assertIn("ARTICLES:", user_prompt)
        self.assertIn("mid-credits scene shows a cameo", user_prompt)
        self.assertIn("only from the articles", user_prompt.lower())
        self.assertNotIn("search_reddit", user_prompt)

    async def test_ollama_error_returns_empty_eggs_not_invented(self):
        analyzer = MovieInsights(
            ollama_host="http://ollama.test", ollama_model="llama3.1:8b"
        )
        analyzer._chat_json = AsyncMock(side_effect=RuntimeError("down"))
        with patch(
            "src.insights.gather_article_corpus",
            AsyncMock(
                return_value={
                    "urls": ["https://example.com/a"],
                    "text": "Some article text about credits.",
                }
            ),
        ):
            eggs, urls = await analyzer.extract_easter_eggs(
                {"title": "Nope", "overview": "", "keywords": []}
            )
        self.assertEqual(eggs, [])
        self.assertEqual(urls, ["https://example.com/a"])


class OllamaTimeoutTests(unittest.TestCase):
    def test_chat_timeout_is_at_least_240s(self):
        with open("src/insights.py", encoding="utf-8") as fh:
            src = fh.read()
        self.assertIn("timeout=420.0", src)
        self.assertNotIn("timeout=120.0", src)
        self.assertNotIn("timeout=180.0", src)
        self.assertNotIn("timeout=240.0", src)


class SourceRemovalTests(unittest.TestCase):
    def test_src_does_not_call_reddit(self):
        import pathlib

        root = pathlib.Path("src")
        for path in root.glob("*.py"):
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("search_reddit", text, path)
            self.assertNotIn("reddit.com/search", text, path)
            self.assertNotIn("AsyncOpenAI", text, path)
            self.assertNotIn("imdb.com/title", text, path)
