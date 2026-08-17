"""GET /search helpers: TTL cache + single-flight TMDB, Postgres fallback.

Does not scrape or enqueue extract jobs. Concurrent identical queries
share one TMDB call (asyncio Future map).
"""

import asyncio
from datetime import datetime, timedelta
from typing import Any, Awaitable, Callable, Dict, List, Optional

GET_SEARCH_TTL = timedelta(minutes=10)

_get_search_cache: Dict[str, Any] = {}
_get_search_inflight: Dict[str, asyncio.Future] = {}

TmdbSearch = Callable[..., Awaitable[List[Dict[str, Any]]]]
DbSearch = Callable[..., Awaitable[List[Dict[str, Any]]]]


def get_search_cache_key(query: str, year: Optional[int]) -> str:
    return f"{query.casefold()}|{year}"


def reset_get_search_state():
    _get_search_cache.clear()
    _get_search_inflight.clear()


def _cache_get(key: str):
    hit = _get_search_cache.get(key)
    if not hit:
        return None
    expires_at, payload = hit
    if datetime.now() >= expires_at:
        _get_search_cache.pop(key, None)
        return None
    return payload


def shape_get_search_item(
    item: Dict[str, Any], image_base: str
) -> Dict[str, Any]:
    poster = item.get("posterPath")
    if poster is None:
        poster = item.get("poster_path")
        if poster and not str(poster).startswith("http"):
            poster = f"{image_base}{poster}"
    year = item.get("year")
    if year is None:
        release = item.get("release_date") or ""
        if len(release) >= 4 and release[:4].isdigit():
            year = int(release[:4])
    return {
        "id": item.get("id"),
        "title": item.get("title"),
        "year": year,
        "posterPath": poster,
        "overview": item.get("overview") or "",
    }


def get_search_payload(
    query: str, items: List[Dict[str, Any]], image_base: str
) -> Dict[str, Any]:
    results = [shape_get_search_item(item, image_base) for item in items]
    return {"query": query, "count": len(results), "results": results}


async def fetch_get_search(
    query: str,
    year: Optional[int],
    tmdb_search: TmdbSearch,
    db_search: DbSearch,
    image_base: str,
) -> Dict[str, Any]:
    """TMDB list search; on failure, local Postgres ILIKE. No extract."""
    try:
        items = await tmdb_search(query, year)
        return get_search_payload(query, items, image_base)
    except Exception as exc:
        print(f"⚠️  TMDB GET /search failed, falling back to Postgres: {exc}")
        rows = await db_search(query, year)
        return get_search_payload(query, rows, image_base)


async def get_search_list(
    query: str,
    year: Optional[int],
    tmdb_search: TmdbSearch,
    db_search: DbSearch,
    image_base: str,
) -> Dict[str, Any]:
    q = (query or "").strip()
    if not q:
        return {"query": query or "", "count": 0, "results": []}
    key = get_search_cache_key(q, year)
    hit = _cache_get(key)
    if hit is not None:
        return hit
    fut = _get_search_inflight.get(key)
    mine = False
    if fut is None:
        fut = asyncio.get_running_loop().create_future()
        _get_search_inflight[key] = fut
        mine = True
    if not mine:
        return await fut
    try:
        payload = await fetch_get_search(
            q, year, tmdb_search, db_search, image_base
        )
        _get_search_cache[key] = (datetime.now() + GET_SEARCH_TTL, payload)
        fut.set_result(payload)
        return payload
    except Exception as exc:
        if not fut.done():
            fut.set_exception(exc)
        raise
    finally:
        if _get_search_inflight.get(key) is fut:
            del _get_search_inflight[key]
