"""TMDB keywords + live web articles + Ollama extract. No Reddit/IMDb."""

import json
import os
import re
from typing import Dict, List, Optional, Tuple
from urllib.parse import parse_qs, unquote, urljoin, urlparse

import httpx

from src.models import EasterEgg, PostCreditsScene, MovieInsightsData
from src.telemetry import record_ollama_duration, start_span

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
        text = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", html)
        text = re.sub(r"(?is)<[^>]+>", " ", text)
        text = re.sub(r"\s+", " ", text)
    return text.strip()


def _ddg_unwrap(href: str) -> str:
    """Unwrap DDG /l/?uddg= redirects, including relative /l/? paths."""
    if not href:
        return ""
    href = href.replace("&amp;", "&").strip()
    if href.startswith("//"):
        href = "https:" + href
    elif href.startswith("/l/"):
        href = "https://duckduckgo.com" + href
    parsed = urlparse(href)
    host = (parsed.netloc or "").lower()
    if "duckduckgo.com" in host and parsed.path.startswith("/l/"):
        qs = parse_qs(parsed.query)
        if qs.get("uddg"):
            return unquote(qs["uddg"][0])
    # relative path with uddg but no host (defensive)
    if parsed.path.startswith("/l/") and "uddg=" in (parsed.query or href):
        qs = parse_qs(parsed.query or href.split("?", 1)[-1])
        if qs.get("uddg"):
            return unquote(qs["uddg"][0])
    return href


def _brave_unwrap(href: str) -> str:
    if not href:
        return ""
    href = href.replace("&amp;", "&").strip()
    parsed = urlparse(href)
    qs = parse_qs(parsed.query)
    if qs.get("click_url"):
        return unquote(qs["click_url"][0])
    if href.startswith("/a/redirect") and "click_url=" in href:
        qs = parse_qs(href.split("?", 1)[-1])
        if qs.get("click_url"):
            return unquote(qs["click_url"][0])
    return href


def _usable_url(href: str) -> str:
    url = _brave_unwrap(_ddg_unwrap(href))
    if not url:
        return ""
    if url.startswith("//"):
        url = "https:" + url
    if not url.startswith("http"):
        return ""
    host = urlparse(url).netloc.lower().lstrip("www.")
    if not host or host in SKIP_HOSTS:
        return ""
    if any(host == s or host.endswith("." + s) for s in SKIP_HOSTS):
        return ""
    return url


def _ddg_hrefs(html: str) -> List[str]:
    hrefs = re.findall(r'class="result__a"[^>]*href="([^"]*)"', html)
    if not hrefs:
        hrefs = re.findall(r'href="([^"]*)"[^>]*class="result__a"', html)
    if not any(hrefs):
        hrefs = re.findall(r'href="(/l/\?[^"]+|https?://[^"]+)"', html)
    return [h for h in hrefs if h]


def _brave_hrefs(html: str) -> List[str]:
    hrefs = re.findall(
        r'class="result-wrapper[^"]*"[\s\S]{0,1500}?href="([^"]+)"',
        html,
    )
    if not hrefs:
        hrefs = re.findall(r'href="(https?://[^"]+)"', html)
    hrefs += re.findall(r'href="(/a/redirect\?[^"]+)"', html)
    return [h for h in hrefs if h]


class MovieInsights:
    def __init__(self):
        self.tmdb_key = os.getenv("TMDB_API_KEY", "")
        self.tmdb_base = "https://api.themoviedb.org/3"
        self.ollama_host = os.getenv("OLLAMA_HOST", "http://100.67.63.33:11434").rstrip("/")
        self.ollama_model = os.getenv("OLLAMA_MODEL", "llama3.1:8b")

    async def keywords_for_movie(self, movie_id: int) -> List[Dict]:
        if not movie_id or not self.tmdb_key:
            return []
        url = f"{self.tmdb_base}/movie/{movie_id}/keywords"
        async with httpx.AsyncClient(timeout=20.0) as client:
            r = await client.get(url, params={"api_key": self.tmdb_key})
            r.raise_for_status()
            return r.json().get("keywords") or []

    def _credits_from_keywords(self, keywords: List[Dict]) -> PostCreditsScene:
        ids = {int(k.get("id")) for k in keywords if k.get("id") is not None}
        has_post = TMDB_POST_CREDITS in ids
        has_mid = TMDB_MID_CREDITS in ids
        count = int(has_post) + int(has_mid)
        names = ", ".join(
            k.get("name", "")
            for k in keywords
            if k.get("id") in (TMDB_POST_CREDITS, TMDB_MID_CREDITS)
        )
        hint = None
        if has_mid and has_post:
            hint = "Mid-credits and post-credits scenes (TMDB)."
        elif has_mid:
            hint = "Mid-credits scene (TMDB)."
        elif has_post:
            hint = "Post-credits scene (TMDB)."
        return PostCreditsScene(
            has_scene=count > 0,
            scene_count=count,
            descriptions=[names] if names else [],
            worth_staying=True if count else False,
            spoiler_free_hint=hint,
        )

    def _add_urls(self, urls: List[str], hrefs: List[str]) -> List[str]:
        for href in hrefs:
            if isinstance(href, tuple):
                href = next((x for x in href if x), "")
            if not href:
                continue
            url = _usable_url(href)
            if not url or url in urls:
                continue
            urls.append(url)
            if len(urls) >= 5:
                break
        return urls

    async def search_article_urls(self, title: str, year: Optional[int]) -> List[str]:
        label = f"{title} {year}" if year else title
        queries = [
            f"{label} easter eggs",
            f"{label} post-credits scene",
        ]
        urls: List[str] = []
        headers = {
            "User-Agent": UA,
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "en-US,en;q=0.9",
        }
        async with httpx.AsyncClient(timeout=20.0, follow_redirects=True, headers=headers) as client:
            for q in queries:
                ddg_ok = False
                try:
                    r = await client.post(
                        "https://html.duckduckgo.com/html/",
                        data={"q": q},
                    )
                    print(
                        f"  DDG status={r.status_code} html_len={len(r.text)} q={q!r}",
                        flush=True,
                    )
                    if r.status_code == 200 and "anomaly-modal" not in r.text:
                        hrefs = _ddg_hrefs(r.text)
                        before = len(urls)
                        self._add_urls(urls, hrefs)
                        ddg_ok = len(urls) > before
                    else:
                        print("  DDG blocked or challenge; will try Brave", flush=True)
                except Exception as e:
                    print(f"  ⚠️  DDG search failed ({q}): {e}", flush=True)
                if len(urls) >= 5:
                    print(f"  search urls: {len(urls)}", flush=True)
                    for u in urls:
                        print(f"  search url: {u}", flush=True)
                    return urls
                if ddg_ok:
                    continue
                try:
                    br = await client.get(
                        "https://search.brave.com/search",
                        params={"q": q},
                    )
                    print(
                        f"  Brave status={br.status_code} html_len={len(br.text)} q={q!r}",
                        flush=True,
                    )
                    if br.status_code == 200:
                        self._add_urls(urls, _brave_hrefs(br.text))
                except Exception as e:
                    print(f"  ⚠️  Brave search failed ({q}): {e}", flush=True)
                if len(urls) >= 5:
                    break
        print(f"  search urls: {len(urls)}", flush=True)
        for u in urls[:5]:
            print(f"  search url: {u}", flush=True)
        return urls[:5]

    async def fetch_articles(self, urls: List[str]) -> List[Tuple[str, str]]:
        articles = []
        headers = {"User-Agent": UA, "Accept": "text/html"}
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True, headers=headers) as client:
            for url in urls:
                try:
                    r = await client.get(url)
                    if r.status_code != 200 or "text/html" not in (r.headers.get("content-type") or ""):
                        continue
                    text = _strip_html(r.text)
                    if len(text) < 400:
                        continue
                    articles.append((url, text[:3000]))
                except Exception as e:
                    print(f"  ⚠️  fetch {url}: {e}")
                if sum(len(t) for _, t in articles) > 8000:
                    break
        print(f"  articles: {len(articles)}")
        for u, txt in articles:
            print(f"  article: {u} chars={len(txt)}")
        return articles

    async def eggs_from_ollama(
        self, title: str, year: Optional[int], articles: List[Tuple[str, str]]
    ) -> List[EasterEgg]:
        if not articles:
            print("  ⚠️  no articles; skip Ollama")
            return []
        label = f"{title} ({year})" if year else title
        use = articles[:2]
        chunks = []
        for url, text in use:
            chunks.append(f"SOURCE: {url}\n{text}\n")
        context = "\n---\n".join(chunks)[:5000]
        prompt = (
            f"Read the articles about {label}. Extract easter eggs, cameos, "
            f"hidden details, and post-credits / mid-credits facts that the articles state.\n\n"
            f"{context}\n\n"
            "Return JSON only: {\"easter_eggs\": [{\"detail\": \"\", \"significance\": \"\", "
            "\"confidence\": \"high|medium|low\"}]}\n"
            "Only use facts from the articles. If the articles have none, return {\"easter_eggs\": []}."
        )
        body = {
            "model": self.ollama_model,
            "messages": [
                {
                    "role": "system",
                    "content": "Extract movie easter eggs from the provided articles. JSON only. Never invent.",
                },
                {"role": "user", "content": prompt},
            ],
            "stream": False,
            "format": "json",
            "options": {"num_predict": 600, "temperature": 0.1},
        }
        import time
        t0 = time.monotonic()
        with start_span(
            "ollama.extract",
            **{
                "movie.title": title or "",
                "movie.year": year or 0,
                "ollama.model": self.ollama_model,
                "ollama.host": self.ollama_host,
                "article.count": len(use),
            },
        ) as span:
          try:
            print(f"  Ollama prompt_chars={len(prompt)} articles={len(use)}", flush=True)
            async with httpx.AsyncClient(timeout=420.0) as client:
                r = await client.post(f"{self.ollama_host}/api/chat", json=body)
                r.raise_for_status()
                data = r.json()
            raw = (data.get("message") or {}).get("content") or "{}"
            parsed = json.loads(raw) if isinstance(raw, str) else raw
            if isinstance(parsed, list):
                parsed = {"easter_eggs": parsed}
            eggs = []
            for egg in parsed.get("easter_eggs") or []:
                if not isinstance(egg, dict):
                    continue
                detail = (egg.get("detail") or "").strip()
                sig = (egg.get("significance") or "").strip()
                if not detail and not sig:
                    continue
                if sig and sig.lower() not in ("high", "medium", "low") and sig not in detail:
                    if detail:
                        pad = "" if detail[-1] in ".!?" else "."
                        detail = f"{detail}{pad} {sig}"
                    else:
                        detail = sig
                if not detail:
                    continue
                eggs.append(
                    EasterEgg(
                        detail=detail,
                        significance=sig,
                        confidence=egg.get("confidence") or "medium",
                    )
                )
            print(f"  ✓ Ollama eggs: {len(eggs)}")
            span.set_attribute("easter_eggs.count", len(eggs))
            record_ollama_duration((time.monotonic() - t0) * 1000)
            return eggs
          except Exception as e:
            record_ollama_duration((time.monotonic() - t0) * 1000)
            print(f"  ⚠️  Ollama failed: {type(e).__name__}: {e!r}", flush=True)
            raise OllamaExtractError(f"{type(e).__name__}: {e}") from e

    async def scrape_movie_insights(
        self,
        movie_title: str,
        year: Optional[int] = None,
        imdb_id: Optional[str] = None,
        movie_id: Optional[int] = None,
        overview: str = "",
    ) -> Optional[MovieInsightsData]:
        keywords = []
        if movie_id:
            try:
                keywords = await self.keywords_for_movie(movie_id)
                print(f"  TMDB keywords: {len(keywords)}")
            except Exception as e:
                print(f"  ⚠️  TMDB keywords failed: {e}")
        post_credits = self._credits_from_keywords(keywords)
        urls = await self.search_article_urls(movie_title, year)
        articles = await self.fetch_articles(urls)
        eggs = await self.eggs_from_ollama(movie_title, year, articles)
        return MovieInsightsData(
            easter_eggs=eggs,
            post_credits=post_credits,
            discussion_count=0,
            source_urls=[u for u, _ in articles],
        )
