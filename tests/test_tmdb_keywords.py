import os
import unittest
from unittest.mock import patch

os.environ.setdefault("TMDB_API_KEY", "test")
os.environ.setdefault("DATABASE_URL", "postgresql://u:p@localhost/db")

from src.config import settings
from src.tmdb_client import TMDBClient


class FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class FakeClient:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def get(self, url, params=None):
        self.calls.append((url, params or {}))
        return FakeResponse(self.payload)


class TMDBKeywordFetchTests(unittest.IsolatedAsyncioTestCase):
    async def test_get_movie_details_appends_keywords(self):
        client = TMDBClient()
        fake = FakeClient(
            {
                "id": 1,
                "title": "Test",
                "keywords": {
                    "keywords": [
                        {"id": 179430, "name": "post-credits scene"}
                    ]
                },
            }
        )
        with patch("src.tmdb_client.httpx.AsyncClient", return_value=fake):
            data = await client.get_movie_details(1)
        self.assertEqual(data["id"], 1)
        url, params = fake.calls[0]
        self.assertIn("/movie/1", url)
        self.assertEqual(params.get("append_to_response"), "keywords")

    async def test_missing_appended_keywords_uses_dedicated_call(self):
        client = TMDBClient()

        class SequentialClient:
            def __init__(self):
                self.n = 0
                self.calls = []

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

            async def get(self, url, params=None):
                self.calls.append(url)
                self.n += 1
                if "keywords" in url and "/movie/9/keywords" in url:
                    return FakeResponse(
                        {"keywords": [{"id": 179431, "name": "mid-credits scene"}]}
                    )
                return FakeResponse({"id": 9, "title": "Test"})

        fake = SequentialClient()
        with patch("src.tmdb_client.httpx.AsyncClient", return_value=fake):
            data = await client.get_movie_details(9)
        self.assertEqual(data["keywords"]["keywords"][0]["id"], 179431)
        self.assertTrue(any("/keywords" in url for url in fake.calls))


class ConfigTests(unittest.TestCase):
    def test_ollama_defaults_and_openai_optional(self):
        self.assertEqual(settings.ollama_host, "http://100.67.63.33:11434")
        self.assertEqual(settings.ollama_model, "llama3.1:8b")
        self.assertEqual(settings.openai_api_key, "")
