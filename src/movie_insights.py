"""TMDB keywords + live web articles + Ollama extract. No Reddit/IMDb."""

import json
import os
import re
from typing import Dict, List, Optional, Tuple
from urllib.parse import parse_qs, unquote, urljoin, urlparse

import httpx

from src.models import EasterEgg, PostCreditsScene, MovieInsightsData
from src.telemetry import record_ollama_duration, start_span
from src.insight_filters import filter_eggs_to_overview, filter_on_title_articles

class OllamaExtractError(RuntimeError):
    """Ollama timed out or returned an error. Not the same as zero eggs."""


TMDB_POST_CREDITS = 179430
TMDB_MID_CREDITS = 179431
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/128.0.0.0 Safari/537.36"
)
SKIP_HOSTS = {
    "duckduckgo.com",
    "html.duckduckgo.com",
    "lite.duckduckgo.com",
    "youtube.com",
    "youtu.be",
    "facebook.com",
    "twitter.com",
    "x.com",
    "instagram.com",
    "tiktok.com",
    "imdb.com",
    "reddit.com",
    "old.reddit.com",
    "brave.com",
    "search.brave.com",
    "cdn.search.brave.com",
    "bing.com",
    "microsoft.com",
    "amazon.com",
    "google.com",
    "googleusercontent.com",
}


def _strip_html(html: str) -> str:
    try:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "noscript"]):
            tag.decompose()
        text = soup.get_text(" ", strip=True)
    except Exception:
        text = re.sub(r"(?is)<(script|style).*?>.*?</\\1>", " ", html)
        text = re.sub(r"(?is)<[^>]+>", " ", text)
        text = re.sub(r"\s+", " ", text)
    return text.strip()
