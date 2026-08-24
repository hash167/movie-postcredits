"""Keep extract articles and eggs on the TMDB title/overview."""

from __future__ import annotations

import re
import unicodedata
from typing import Any, Iterable, List, Optional, Sequence, Tuple

_STOP = {
    "the", "and", "for", "from", "with", "that", "this", "into", "over",
    "movie", "film", "a", "an", "of", "in", "on", "to", "at", "by",
}

_FOREIGN = (
    "superman",
    "peacemaker",
    "justice league",
    "justice gang",
    "hall of justice",
    "action comics",
    "batman",
    "wonder woman",
    "spider-man",
    "spiderman",
    "marvel cinematic",
    "star wars",
    "harry potter",
    "dceu",
    " mcu",
    "dcu",
)


def _fold(s: str) -> str:
    n = unicodedata.normalize("NFKD", s or "")
    return "".join(c for c in n if not unicodedata.combining(c)).lower()


def title_tokens(title: str) -> set[str]:
    folded = _fold(title)
    words = re.findall(r"[a-z0-9]+", folded)
    return {w for w in words if len(w) >= 3 and w not in _STOP}


def overview_tokens(overview: str) -> set[str]:
    folded = _fold(overview)
    words = re.findall(r"[a-z0-9]+", folded)
    out = set()
    for w in words:
        if len(w) >= 4 and w not in _STOP:
            out.add(w)
    return out


def article_is_about_title(
    url: str,
    text: str,
    title: str,
    year: Optional[int] = None,
    imdb_id: Optional[str] = None,
) -> bool:
    hay = _fold(f"{url}\n{(text or '')[:4000]}")
    if imdb_id and imdb_id.lower() in hay:
        return True
    title_l = _fold(title).strip()
    if title_l and title_l in hay:
        return True
    toks = title_tokens(title)
    if toks and all(t in hay for t in toks):
        return True
    return False


def filter_on_title_articles(
    articles: Sequence[Tuple[str, str]],
    title: str,
    year: Optional[int] = None,
    imdb_id: Optional[str] = None,
) -> List[Tuple[str, str]]:
    kept = []
    for url, text in articles:
        if article_is_about_title(url, text, title, year, imdb_id):
            kept.append((url, text))
        else:
            print(f"  skip off-title article: {url}", flush=True)
    return kept


def egg_fits_overview(detail: str, title: str, overview: str) -> bool:
    blob = _fold(detail)
    if not blob:
        return False
    ctx = _fold(f"{title} {overview}")
    for mark in _FOREIGN:
        if mark.strip() in blob and mark.strip() not in ctx:
            return False
    needles = title_tokens(title) | overview_tokens(overview)
    long = {t for t in needles if len(t) >= 4}
    if long and any(t in blob for t in long):
        return True
    if not any(mark.strip() in blob for mark in _FOREIGN):
        egg_names = {w for w in re.findall(r"[a-z0-9]+", blob) if len(w) >= 5 and w not in _STOP}
        if egg_names and long and not (egg_names & long):
            return False
        return True
    return False


def filter_eggs_to_overview(
    eggs: Iterable[Any],
    title: str,
    overview: str,
) -> List[Any]:
    kept: List[Any] = []
    for egg in eggs:
        if egg_fits_overview(egg.detail or "", title, overview):
            kept.append(egg)
        else:
            print(f"  drop off-overview egg: {(egg.detail or '')[:80]}", flush=True)
    return kept
