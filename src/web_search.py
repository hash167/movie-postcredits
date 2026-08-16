"""Live web search + article fetch (no paid keys).

DuckDuckGo HTML search, then download a few result pages so Ollama
can extract easter eggs from current articles instead of training data.
"""

import html as html_lib
import re
from typing import Dict, List, Optional
from urllib.parse import parse_qs, unquote, urlparse

import httpx
from bs4 import BeautifulSoup

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/128.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

DDG_HTML = "https://html.duckduckgo.com/html/"
MAX_RESULTS = 5
MAX_TOTAL_CHARS = 10000
MAX_PER_ARTICLE = 4000
SEARCH_TIMEOUT = 20.0
FETCH_TIMEOUT = 15.0

SKIP_HOST_PARTS = (
    "duckduckgo.com",
    "google.com",
    "bing.com",
    "youtube.com",
    "youtu.be",
    "facebook.com",
    "twitter.com",
    "x.com",
    "instagram.com",
    "tiktok.com",
    "reddit.com",
)


def search_queries(title: str, year: Optional[int] = None) -> List[str]:
    year_bit = f" {year}" if year else ""
    return [
        f"{title}{year_bit} easter eggs",
        f"{title}{year_bit} post-credits scene",
    ]


def decode_ddg_url(href: str) -> Optional[str]:
    """Turn a DDG result href into a real http(s) URL."""
    if not href:
        return None
    href = html_lib.unescape(href).strip()
    if href.startswith("//"):
        href = "https:" + href
    parsed = urlparse(href)
    if parsed.netloc.endswith("duckduckgo.com"):
        qs = parse_qs(parsed.query)
        if qs.get("uddg"):
            href = unquote(qs["uddg"][0])
            parsed = urlparse(href)
    if parsed.scheme not in ("http", "https"):
        return None
    host = (parsed.netloc or "").lower()
    if any(part in host for part in SKIP_HOST_PARTS):
        return None
    return href


def parse_ddg_result_urls(html_text: str, limit: int = MAX_RESULTS) -> List[str]:
    """Extract unique result URLs from DuckDuckGo HTML search markup."""
    soup = BeautifulSoup(html_text or "", "html.parser")
    urls = []
    seen = set()
    for anchor in soup.select("a.result__a, a.result__url"):
        href = anchor.get("href") or ""
        url = decode_ddg_url(href)
        if not url or url in seen:
            continue
        seen.add(url)
        urls.append(url)
        if len(urls) >= limit:
            break
    if not urls:
        for match in re.finditer(r'uddg=([^&"\']+)', html_text or ""):
            url = decode_ddg_url("https://duckduckgo.com/l/?uddg=" + match.group(1))
            if not url or url in seen:
                continue
            seen.add(url)
            urls.append(url)
            if len(urls) >= limit:
                break
    return urls


def html_to_text(html_text: str) -> str:
    soup = BeautifulSoup(html_text or "", "html.parser")
    for tag in soup(["script", "style", "noscript", "nav", "footer", "header"]):
        tag.decompose()
    text = soup.get_text(separator="\n")
    lines = [re.sub(r"\s+", " ", line).strip() for line in text.splitlines()]
    return "\n".join(line for line in lines if line)


async def search_duckduckgo(query: str, limit: int = MAX_RESULTS) -> List[str]:
    params = {"q": query}
    try:
        async with httpx.AsyncClient(
            timeout=SEARCH_TIMEOUT, follow_redirects=True, headers=BROWSER_HEADERS
        ) as client:
            response = await client.get(DDG_HTML, params=params)
            if response.status_code >= 400:
                response = await client.post(DDG_HTML, data=params)
            if response.status_code != 200:
                print(f"  ⚠️  DuckDuckGo search HTTP {response.status_code} for {query!r}")
                return []
            return parse_ddg_result_urls(response.text, limit=limit)
    except Exception as exc:
        print(f"  ⚠️  DuckDuckGo search failed for {query!r}: {exc}")
        return []


async def fetch_article_text(url: str) -> str:
    try:
        async with httpx.AsyncClient(
            timeout=FETCH_TIMEOUT, follow_redirects=True, headers=BROWSER_HEADERS
        ) as client:
            response = await client.get(url)
            if response.status_code != 200:
                print(f"  ⚠️  Skip article HTTP {response.status_code}: {url}")
                return ""
            ctype = (response.headers.get("content-type") or "").lower()
            if "html" not in ctype and "text/" not in ctype:
                return ""
            return html_to_text(response.text)[:MAX_PER_ARTICLE]
    except Exception as exc:
        print(f"  ⚠️  Skip article {url}: {exc}")
        return ""


async def gather_article_corpus(
    title: str, year: Optional[int] = None
) -> Dict[str, object]:
    """Search the live web and return capped article text + source URLs."""
    urls: List[str] = []
    seen = set()
    for query in search_queries(title, year):
        print(f"  🔎 Web search: {query}")
        for url in await search_duckduckgo(query, limit=MAX_RESULTS):
            if url in seen:
                continue
            seen.add(url)
            urls.append(url)
            if len(urls) >= MAX_RESULTS:
                break
        if len(urls) >= MAX_RESULTS:
            break

    chunks = []
    used_urls = []
    total = 0
    for url in urls:
        if total >= MAX_TOTAL_CHARS:
            break
        text = await fetch_article_text(url)
        if not text or len(text) < 80:
            continue
        budget = MAX_TOTAL_CHARS - total
        snippet = text[: min(MAX_PER_ARTICLE, budget)]
        chunks.append(f"SOURCE: {url}\n{snippet}")
        used_urls.append(url)
        total += len(snippet)

    corpus = "\n\n-----\n\n".join(chunks)
    print(f"  📰 Fetched {len(used_urls)} articles ({len(corpus)} chars)")
    return {"urls": used_urls, "text": corpus}
