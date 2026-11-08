"""Validate Ollama-extracted easter eggs before upsert/serve.

Check order (first failure drops the egg, unless a safe cast correction applies):

1. Non-empty detail
2. Overview / foreign-franchise filter (insight_filters.egg_fits_overview)
3. Cast grounding — actor↔character claims vs TMDB credits
4. Source grounding — claim must be supportable from fetched article text;
   strip or reject unsupported significance fluff (Aquaman/Guardians-style nods)
5. Prefer real easter eggs over bare plot/character bios

Fail behavior: drop the egg (log reason). Cast mismatches are never rewritten
— role attributes in the same sentence are often swapped too.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from src.insight_filters import _fold, egg_fits_overview

_STOP = {
    "the", "and", "for", "from", "with", "that", "this", "into", "over",
    "movie", "film", "a", "an", "of", "in", "on", "to", "at", "by", "is",
    "as", "his", "her", "their", "who", "was", "are", "been", "being",
    "character", "appears", "plays", "role", "scene", "after", "before",
    "about", "when", "where", "which", "while", "during", "between",
}

_EGG_MARKERS = (
    "easter egg",
    "cameo",
    "reference",
    "refers to",
    "nod to",
    "nods to",
    "homage",
    "hidden",
    "blink",
    "post-credit",
    "post credit",
    "mid-credit",
    "mid credit",
    "after the credits",
    "during the credits",
    "background",
    "poster",
    "prop ",
    " prop",
    "easter",
    "cameos",
    "callback",
    "payoff",
    "foreshadow",
)

_SIGNIFICANCE_FLUFF = (
    "aquaman",
    "guardians of the galaxy",
    "guardian of the galaxy",
    "justice league",
    "dceu",
    " mcu",
    "marvel cinematic",
    "star wars",
    "harry potter",
)

_NAME = r"[A-Z][A-Za-z0-9.-]+(?:\s+[A-Z][A-Za-z0-9.-]+){0,3}"

_ACTOR_CHAR_PATTERNS = [
    # Jason Momoa's character, James / Jason Momoa’s character James
    re.compile(
        rf"(?P<actor>{_NAME})(?:'s|’s)\s+character(?:,)?\s+(?P<char>{_NAME})",
        re.I,
    ),
    # Jason Momoa as Jonny Hale / plays / portrays
    re.compile(
        rf"(?P<actor>{_NAME})\s+(?:as|plays|portraying|portrays|playing)\s+(?P<char>{_NAME})",
        re.I,
    ),
]


@dataclass
class CastMember:
    actor: str
    character: str
    actor_fold: str = ""
    character_fold: str = ""
    character_tokens: Tuple[str, ...] = ()

    def __post_init__(self):
        self.actor_fold = _fold(self.actor)
        self.character_fold = _fold(self.character)
        toks = tuple(
            t for t in re.findall(r"[a-z0-9]+", self.character_fold)
            if len(t) >= 3 and t not in _STOP
        )
        self.character_tokens = toks


@dataclass
class ValidationResult:
    kept: List[Any] = field(default_factory=list)
    dropped: List[Tuple[Any, str]] = field(default_factory=list)
    corrected: List[Tuple[Any, str]] = field(default_factory=list)


def cast_from_tmdb(credits_cast: Sequence[Dict[str, Any]]) -> List[CastMember]:
    out: List[CastMember] = []
    for row in credits_cast or []:
        actor = (row.get("name") or "").strip()
        character = (row.get("character") or "").strip()
        if not actor:
            continue
        # Drop credit parentheses like "James Hale (young)"
        character = re.sub(r"\s*\([^)]*\)\s*", " ", character).strip()
        out.append(CastMember(actor=actor, character=character))
    return out


def _name_in_text(name_fold: str, blob: str) -> bool:
    if not name_fold or len(name_fold) < 3:
        return False
    # Word-boundary-ish: avoid matching "jon" inside "jonathan" via spaces
    return f" {name_fold} " in f" {blob} " or blob.startswith(name_fold + " ") or blob.endswith(" " + name_fold)


def _find_cast_mentions(detail: str, cast: Sequence[CastMember]) -> Tuple[List[CastMember], List[CastMember]]:
    """Return (actors mentioned, characters mentioned) from cast list."""
    blob = _fold(detail)
    actors: List[CastMember] = []
    chars: List[CastMember] = []
    for m in cast:
        if _name_in_text(m.actor_fold, blob):
            actors.append(m)
        # Match full character or distinctive first/last token (len>=4)
        if m.character_fold and _name_in_text(m.character_fold, blob):
            chars.append(m)
        else:
            for tok in m.character_tokens:
                if len(tok) >= 4 and _name_in_text(tok, blob):
                    chars.append(m)
                    break
    # de-dupe preserving order
    def uniq(items: List[CastMember]) -> List[CastMember]:
        seen = set()
        out = []
        for i in items:
            key = i.actor_fold
            if key in seen:
                continue
            seen.add(key)
            out.append(i)
        return out

    return uniq(actors), uniq(chars)


def _explicit_actor_char_pairs(detail: str) -> List[Tuple[str, str]]:
    pairs = []
    for pat in _ACTOR_CHAR_PATTERNS:
        for m in pat.finditer(detail or ""):
            actor = (m.group("actor") or "").strip()
            char = (m.group("char") or "").strip()
            # Trim trailing punctuation / conjunctions
            char = re.sub(r"[,:;].*$", "", char).strip()
            if actor and char:
                pairs.append((actor, char))
    return pairs


def _char_matches_member(char_name: str, member: CastMember) -> bool:
    cf = _fold(char_name)
    if not cf:
        return False
    if cf == member.character_fold or member.character_fold.startswith(cf + " ") or cf.startswith(member.character_fold + " "):
        return True
    toks = [t for t in re.findall(r"[a-z0-9]+", cf) if len(t) >= 3 and t not in _STOP]
    if not toks:
        return False
    # All tokens of the claim appear in the credit character
    return all(t in member.character_fold for t in toks) and any(len(t) >= 4 for t in toks)


def _actor_matches_member(actor_name: str, member: CastMember) -> bool:
    af = _fold(actor_name)
    return bool(af) and (af == member.actor_fold or member.actor_fold.endswith(" " + af) or af in member.actor_fold.split())


def check_cast_grounding(
    detail: str,
    cast: Sequence[CastMember],
) -> Tuple[bool, Optional[str], Optional[str]]:
    """Return (ok, reason_if_fail, corrected_detail_or_None)."""
    if not cast or not detail:
        return True, None, None

    explicit = _explicit_actor_char_pairs(detail)
    if explicit:
        for actor_name, char_name in explicit:
            actor_mem = next((m for m in cast if _actor_matches_member(actor_name, m)), None)
            if actor_mem is None:
                continue  # unknown actor name; don't fail solely on that
            if _char_matches_member(char_name, actor_mem):
                continue  # correct pairing
            # Actor↔character swap (or wrong pairing): drop. Do not auto-rewrite —
            # role bios in the same sentence are often swapped too (Wrecking Crew).
            real = actor_mem.character or "?"
            return False, f"cast mismatch: {actor_name} ≠ {char_name} (TMDB: {real})", None
        return True, None, None

    # Implicit: egg mentions both an actor and a character that belong to different people
    actors, chars = _find_cast_mentions(detail, cast)
    if actors and chars:
        for a in actors:
            for c in chars:
                if a.actor_fold == c.actor_fold:
                    continue  # same person — actor's own character mentioned
                # Actor A mentioned alongside character belonging to B → suspicious
                # Only fail when the character token is clearly B's and not also in A's name/character
                if any(tok in _fold(detail) for tok in c.character_tokens if len(tok) >= 4):
                    # If A's character is NOT also mentioned, this is a swap smell
                    a_char_mentioned = any(
                        _name_in_text(tok, _fold(detail))
                        for tok in a.character_tokens
                        if len(tok) >= 4
                    )
                    if not a_char_mentioned:
                        return (
                            False,
                            f"cast swap smell: {a.actor} with {c.character} "
                            f"(TMDB: {a.actor}→{a.character})",
                            None,
                        )
    return True, None, None


def _content_tokens(text: str) -> set[str]:
    return {
        t for t in re.findall(r"[a-z0-9]+", _fold(text or ""))
        if len(t) >= 4 and t not in _STOP
    }


def check_source_grounding(
    detail: str,
    significance: str,
    articles: Sequence[Tuple[str, str]],
) -> Tuple[bool, Optional[str], str, Optional[str]]:
    """Return (ok, reason, cleaned_significance, matched_source_url)."""
    if not articles:
        # No articles → cannot ground; keep only if we somehow got here (shouldn't)
        return False, "no articles to ground against", "", None

    corpus = "\n".join(t for _, t in articles)
    corpus_f = _fold(corpus)
    corpus_toks = _content_tokens(corpus)

    detail_toks = _content_tokens(detail)
    if not detail_toks:
        return False, "empty detail tokens", "", None

    detail_f = _fold(detail)
    # Reject invented franchise significance stuffed into the detail itself
    for mark in _SIGNIFICANCE_FLUFF:
        m = mark.strip()
        if m and m in detail_f and m not in corpus_f:
            return False, f"unsupported franchise claim in detail ({m})", "", None

    # Require a solid fraction of distinctive detail tokens to appear in sources
    overlap = detail_toks & corpus_toks
    substring_hits = sum(1 for t in detail_toks if t in corpus_f)
    support = max(len(overlap), substring_hits)
    ratio = support / max(len(detail_toks), 1)
    need = max(3, min(5, (len(detail_toks) + 1) // 2))
    if support < need or ratio < 0.45:
        return False, f"detail not grounded in articles ({support}/{len(detail_toks)} tokens)", "", None

    # Significance fluff: drop unsupported franchise nods
    sig = (significance or "").strip()
    sig_f = _fold(sig)
    if sig and any(mark.strip() in sig_f for mark in _SIGNIFICANCE_FLUFF):
        if not any(mark.strip() in corpus_f for mark in _SIGNIFICANCE_FLUFF if mark.strip() in sig_f):
            sig = ""  # strip unsupported fluff rather than keeping it

    # If significance has distinctive tokens absent from corpus AND detail, strip it
    if sig:
        sig_toks = _content_tokens(sig) - detail_toks
        if sig_toks and not (sig_toks & corpus_toks):
            # All unique sig tokens missing from sources → strip
            if len(sig_toks - corpus_toks) >= max(2, len(sig_toks) // 2):
                sig = ""

    # Pick a best-matching source URL (most token overlap)
    best_url = None
    best_score = -1
    for url, text in articles:
        score = len(detail_toks & _content_tokens(text))
        if score > best_score:
            best_score = score
            best_url = url

    return True, None, sig, best_url


def looks_like_plot_bio(detail: str) -> bool:
    """True for bare character bios that are not framed as eggs."""
    blob = _fold(detail or "")
    if not blob:
        return True
    if any(m in blob for m in _EGG_MARKERS):
        return False
    # "X's character, Y, is a ..." / "X plays Y, a suspended detective"
    bioish = bool(
        re.search(
            r"\bcharacter\b.*\bis (a|an|the)\b|\bplays\b.*\bis (a|an|the)\b|"
            r"\bportrays\b|\bis a (us )?navy seal\b|\bis a suspended\b|"
            r"\bhalf-?brothers?\b.*\breunite\b",
            blob,
        )
    )
    return bioish


def validate_egg(
    egg: Any,
    *,
    title: str,
    overview: str,
    cast: Sequence[CastMember],
    articles: Sequence[Tuple[str, str]],
    prefer_eggs: bool = True,
) -> Tuple[Optional[Any], Optional[str], bool]:
    """Validate one egg. Returns (egg_or_None, drop_reason, was_corrected)."""
    detail = (getattr(egg, "detail", None) or "").strip()
    significance = (getattr(egg, "significance", None) or "").strip()
    if not detail:
        return None, "empty detail", False

    if not egg_fits_overview(detail, title, overview or ""):
        return None, "overview/foreign-franchise filter", False

    ok, reason, corrected = check_cast_grounding(detail, cast)
    was_corrected = False
    if not ok:
        return None, reason or "cast grounding failed", False
    if corrected:
        detail = corrected
        was_corrected = True
        try:
            egg.detail = detail
        except Exception:
            pass

    ok, reason, cleaned_sig, source_url = check_source_grounding(detail, significance, articles)
    if not ok:
        return None, reason or "source grounding failed", was_corrected

    if prefer_eggs and looks_like_plot_bio(detail):
        return None, "plot/character bio (not an easter egg)", was_corrected

    try:
        if cleaned_sig != significance:
            egg.significance = cleaned_sig
        if source_url and not getattr(egg, "source_url", None):
            egg.source_url = source_url
        if was_corrected:
            egg.detail = detail
    except Exception:
        pass

    return egg, None, was_corrected


def validate_eggs(
    eggs: Iterable[Any],
    *,
    title: str,
    overview: str,
    cast: Sequence[CastMember] | Sequence[Dict[str, Any]],
    articles: Sequence[Tuple[str, str]],
    prefer_eggs: bool = True,
) -> ValidationResult:
    if cast and isinstance(cast[0], dict):
        cast_members = cast_from_tmdb(cast)  # type: ignore[arg-type]
    else:
        cast_members = list(cast)  # type: ignore[arg-type]

    result = ValidationResult()
    for egg in eggs:
        kept, reason, corrected = validate_egg(
            egg,
            title=title,
            overview=overview,
            cast=cast_members,
            articles=articles,
            prefer_eggs=prefer_eggs,
        )
        if kept is None:
            result.dropped.append((egg, reason or "rejected"))
            print(f"  drop egg [{reason}]: {(getattr(egg, 'detail', '') or '')[:90]}", flush=True)
        else:
            result.kept.append(kept)
            if corrected:
                result.corrected.append((kept, "cast auto-corrected"))
                print(
                    f"  corrected cast in egg: {(getattr(kept, 'detail', '') or '')[:90]}",
                    flush=True,
                )
    return result
