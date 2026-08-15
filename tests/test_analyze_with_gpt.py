"""Unit tests for IMDb-only vs empty-source analysis (no live APIs)."""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

from src.models import RedditInsights
from src.reddit_scraper import RedditScraper


SAMPLE_ANALYSIS = {
    "post_credits": {
        "has_scene": True,
        "scene_count": 1,
        "descriptions": ["A mid-credits stinger"],
        "worth_staying": True,
        "spoiler_free_hint": "Stay for a teaser",
    },
    "easter_eggs": [
        {
            "detail": "Hidden logo in the last shot",
            "significance": "References the sequel",
            "confidence": "high",
            "source_url": None,
        }
    ],
}

IMDB_DATA = {
    "trivia": ["There is a post-credits scene with the villain."],
    "goofs": ["Continuity error in the last shot."],
    "total_items": 2,
}


def _mock_openai_response(payload: dict) -> MagicMock:
    response = MagicMock()
    response.choices = [MagicMock()]
    response.choices[0].message.content = json.dumps(payload)
    return response


def _make_scraper() -> RedditScraper:
    with patch("src.reddit_scraper.AsyncOpenAI"):
        scraper = RedditScraper()
    scraper.client = MagicMock()
    scraper.client.chat.completions.create = AsyncMock(
        return_value=_mock_openai_response(SAMPLE_ANALYSIS)
    )
    return scraper


def _user_prompt(scraper: RedditScraper) -> str:
    call_kwargs = scraper.client.chat.completions.create.await_args.kwargs
    return call_kwargs["messages"][1]["content"]


def test_imdb_only_data_is_analyzed():
    scraper = _make_scraper()

    result = asyncio.run(
        scraper.analyze_with_gpt("Some Movie", posts=[], imdb_data=IMDB_DATA)
    )

    assert isinstance(result, RedditInsights)
    assert result.post_credits.has_scene is True
    assert result.post_credits.scene_count == 1
    assert result.reddit_discussion_count == 0
    assert result.source_urls == []
    assert len(result.easter_eggs) == 1
    scraper.client.chat.completions.create.assert_awaited_once()

    prompt = _user_prompt(scraper)
    assert "IMDb Trivia" in prompt
    assert "There is a post-credits scene with the villain." in prompt
    assert "Post 1" not in prompt


def test_empty_posts_and_empty_imdb_returns_none():
    scraper = _make_scraper()

    result = asyncio.run(
        scraper.analyze_with_gpt("Some Movie", posts=[], imdb_data=None)
    )
    assert result is None

    result = asyncio.run(
        scraper.analyze_with_gpt(
            "Some Movie",
            posts=[],
            imdb_data={"trivia": [], "goofs": [], "total_items": 0},
        )
    )
    assert result is None
    scraper.client.chat.completions.create.assert_not_awaited()


def test_scrape_movie_insights_analyzes_imdb_only():
    scraper = _make_scraper()
    scraper.search_reddit = AsyncMock(return_value=[])
    scraper.imdb_scraper.get_trivia_and_goofs = AsyncMock(return_value=IMDB_DATA)

    result = asyncio.run(
        scraper.scrape_movie_insights("Some Movie", year=2020, imdb_id="tt1234567")
    )

    assert isinstance(result, RedditInsights)
    scraper.client.chat.completions.create.assert_awaited_once()


def test_scrape_movie_insights_returns_none_when_both_sources_empty():
    scraper = _make_scraper()
    scraper.search_reddit = AsyncMock(return_value=[])
    scraper.imdb_scraper.get_trivia_and_goofs = AsyncMock(
        return_value={"trivia": [], "goofs": [], "total_items": 0}
    )

    result = asyncio.run(
        scraper.scrape_movie_insights("Some Movie", year=2020, imdb_id="tt1234567")
    )

    assert result is None
    scraper.client.chat.completions.create.assert_not_awaited()
