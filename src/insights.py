"""TMDB keywords + live-web articles + Ollama extract.

TMDB keyword 179430 = post-credits scene, 179431 = mid-credits scene.
Those tags are the source of truth for has_scene / scene_count.
Easter eggs come from fetched articles, not the model's training cutoff.
"""

import json
import re
from typing import Any, Dict, List, Optional

import httpx

from src.config import settings
from src.models import EasterEgg, PostCreditsScene, RedditInsights
from src.web_search import gather_article_corpus

KEYWORD_POST_CREDITS = 179430
KEYWORD_MID_CREDITS = 179431


class OllamaExtractError(Exception):
    """Ollama transport, timeout, HTTP, or parse failure — not a real empty extract."""


def extract_keywords(movie_data: Optional[Dict]) -> List[Dict]:
    """Read TMDB keyword objects from a details or /keywords payload."""
    if not movie_data:
        return []
    raw = movie_data.get("keywords")
    if isinstance(raw, dict):
        items = raw.get("keywords") or raw.get("results") or []
    elif isinstance(raw, list):
        items = raw
    else:
        items = []
    return [item for item in items if isinstance(item, dict)]


def keyword_ids(keywords: List[Dict]) -> set:
    ids = set()
    for item in keywords:
        kid = item.get("id")
        if kid is None:
            continue
        try:
            ids.add(int(kid))
        except (TypeError, ValueError):
            continue
    return ids


def post_credits_from_keywords(keywords: List[Dict]) -> PostCreditsScene:
    """Set has_scene / scene_count from TMDB credit-scene keyword tags."""
    ids = keyword_ids(keywords)
    has_mid = KEYWORD_MID_CREDITS in ids
    has_post = KEYWORD_POST_CREDITS in ids
    descriptions = []
    if has_mid:
        descriptions.append("Mid-credits scene")
    if has_post:
        descriptions.append("Post-credits scene")
    scene_count = len(descriptions)
    has_scene = scene_count > 0
    if has_mid and has_post:
        hint = "Stay for a mid-credits scene and a post-credits scene."
    elif has_mid:
        hint = "Stay for a mid-credits scene."
    elif has_post:
        hint = "Stay for a post-credits scene."
    else:
        hint = None
    return PostCreditsScene(
        has_scene=has_scene,
        scene_count=scene_count,
        descriptions=descriptions,
        worth_staying=True if has_scene else False,
        spoiler_free_hint=hint,
    )


def parse_json_content(text: str) -> Dict[str, Any]:
    """Parse a JSON object from model output, including fenced/prose wraps."""
    if not text:
        raise ValueError("empty model output")
    stripped = text.strip()
    try:
        parsed = json.loads(stripped)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass
    fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", stripped, re.S)
    if fenced:
        parsed = json.loads(fenced.group(1))
        if isinstance(parsed, dict):
            return parsed
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start != -1 and end > start:
        parsed = json.loads(stripped[start : end + 1])
        if isinstance(parsed, dict):
            return parsed
    raise ValueError("no JSON object in model output")


def eggs_from_model_payload(payload: Dict[str, Any]) -> List[EasterEgg]:
    eggs = []
    for egg in payload.get("easter_eggs") or []:
        if not isinstance(egg, dict):
            continue
        detail = (egg.get("detail") or egg.get("description") or "").strip()
        if not detail:
            continue
        significance = (egg.get("significance") or "").strip()[:50]
        eggs.append(
            EasterEgg(
                detail=detail,
                significance=significance,
                confidence=egg.get("confidence") or "medium",
                source_url=egg.get("source_url"),
            )
        )
    return eggs


class MovieInsights:
    """Build persisted insights from TMDB details and optional Ollama."""

    def __init__(
        self,
        ollama_host: Optional[str] = None,
        ollama_model: Optional[str] = None,
    ):
        self.ollama_host = (ollama_host or settings.ollama_host).rstrip("/")
        self.ollama_model = ollama_model or settings.ollama_model

    async def analyze_movie(self, details: Dict) -> RedditInsights:
        keywords = extract_keywords(details)
        post_credits = post_credits_from_keywords(keywords)
        print(
            f"  TMDB keywords: mid={KEYWORD_MID_CREDITS in keyword_ids(keywords)} "
            f"post={KEYWORD_POST_CREDITS in keyword_ids(keywords)} "
            f"has_scene={post_credits.has_scene} scene_count={post_credits.scene_count}"
        )
        eggs, source_urls = await self.extract_easter_eggs(details, keywords)
        return RedditInsights(
            easter_eggs=eggs,
            post_credits=post_credits,
            reddit_discussion_count=len(source_urls),
            source_urls=source_urls,
        )

    async def extract_easter_eggs(
        self, details: Dict, keywords: Optional[List[Dict]] = None
    ) -> tuple:
        """Search live articles, then ask Ollama to extract only that text.

        Returns (eggs, source_urls). If no articles are fetched, eggs are
        empty so upsert_movie will not wipe rows already in Postgres.
        """
        keywords = keywords if keywords is not None else extract_keywords(details)
        title = details.get("title") or "Unknown"
        release_date = details.get("release_date") or ""
        year = details.get("year")
        if not year and release_date and len(release_date) >= 4:
            try:
                year = int(release_date[:4])
            except ValueError:
                year = None
        overview = details.get("overview") or ""
        keyword_names = [
            item.get("name") for item in keywords if item.get("name")
        ]
        year_bit = f" ({year})" if year else ""
        keyword_bit = ", ".join(keyword_names) if keyword_names else "(none)"

        corpus = await gather_article_corpus(title, year)
        article_text = (corpus.get("text") or "").strip()
        source_urls = list(corpus.get("urls") or [])
        if not article_text:
            print("  ⚠️  No live articles found; leaving easter eggs unchanged")
            return [], []

        system_msg = (
            "You extract easter eggs and post-credits hints from the provided "
            "article text only. Respond with a JSON object. Never invent. "
            "If a fact is not clearly stated in the articles, omit it."
        )
        prompt = (
            f'Extract easter eggs / credits hints for "{title}"{year_bit} '
            "ONLY from the articles below.\n\n"
            f"Overview (context, not a source): {overview or '(none)'}\n"
            f"TMDB keywords (context, not a source): {keyword_bit}\n\n"
            "ARTICLES:\n"
            f"{article_text}\n\n"
            "Rules:\n"
            "- Use only facts written in the articles.\n"
            "- Do not use your own knowledge of the movie.\n"
            "- If the articles do not mention eggs or credits scenes, "
            "return an empty easter_eggs array.\n\n"
            "JSON shape:\n"
            "{\n"
            '  "easter_eggs": [\n'
            "    {\n"
            '      "detail": "fact copied from the articles",\n'
            '      "significance": "what it references"\n'
            "    }\n"
            "  ]\n"
            "}\n"
        )
        eggs = await self.eggs_from_ollama(system_msg, prompt)
        print(f"  ✓ Ollama extracted {len(eggs)} eggs from articles")
        return eggs, source_urls

    async def eggs_from_ollama(
        self, system_msg: str, prompt: str
    ) -> List[EasterEgg]:
        """Call Ollama and parse eggs. Raise on transport/HTTP/parse failure.

        A real empty extract (valid JSON with easter_eggs: []) returns [].
        """
        try:
            payload = await self._chat_json(system_msg, prompt)
            return eggs_from_model_payload(payload)
        except OllamaExtractError:
            raise
        except Exception as exc:
            print(f"  ⚠️  Ollama easter-egg extract failed: {exc}")
            raise OllamaExtractError(str(exc)) from exc

    async def fill_insights(self, details: Dict) -> RedditInsights:
        return await self.analyze_movie(details)

    async def _chat_json(self, system_msg: str, prompt: str) -> Dict[str, Any]:
        url = f"{self.ollama_host}/v1/chat/completions"
        body = {
            "model": self.ollama_model,
            "messages": [
                {"role": "system", "content": system_msg},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0,
            "response_format": {"type": "json_object"},
        }
        # CPU llama3.1:8b; worker stale lock is 10 min (> 420s).
        try:
            async with httpx.AsyncClient(timeout=420.0) as client:
                response = await client.post(url, json=body)
                if response.status_code >= 400:
                    # Some Ollama builds reject response_format; retry without it.
                    body.pop("response_format", None)
                    response = await client.post(url, json=body)
                response.raise_for_status()
                data = response.json()
            content = (
                data.get("choices", [{}])[0]
                .get("message", {})
                .get("content", "")
            )
            return parse_json_content(content)
        except OllamaExtractError:
            raise
        except Exception as exc:
            print(f"  ⚠️  Ollama easter-egg extract failed: {exc}")
            raise OllamaExtractError(str(exc)) from exc
