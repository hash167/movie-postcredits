"""Map scraper models onto the live Postgres column names.

Live cluster (movie-api) does NOT have easter_eggs.detail / confidence /
source_url or reddit_insights.discussion_count / source_urls.
post_credits.worth_staying is VARCHAR, not boolean.
"""

from typing import Any, Dict, List, Optional, Union

EASTER_EGG_TITLE_MAX = 500
EASTER_EGG_SIGNIFICANCE_MAX = 50


def egg_to_live_columns(
    detail: str, significance: Optional[str] = None
) -> Dict[str, Any]:
    """Map egg.detail → title (truncated) + description."""
    text = (detail or "").strip()
    title = text[:EASTER_EGG_TITLE_MAX]
    sig = (significance or "").strip()
    if sig:
        sig = sig[:EASTER_EGG_SIGNIFICANCE_MAX]
    else:
        sig = None
    return {
        "title": title or None,
        "description": text or None,
        "timestamp_minutes": None,
        "significance": sig,
    }


def worth_staying_to_db(value: Optional[Union[bool, str]]) -> Optional[str]:
    """Store worth_staying as 'yes' / 'no' / NULL (live VARCHAR column)."""
    if value is True:
        return "yes"
    if value is False:
        return "no"
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in ("yes", "true", "1"):
            return "yes"
        if lowered in ("no", "false", "0"):
            return "no"
    return None


def worth_staying_to_bool(value: Any) -> Optional[bool]:
    """Normalize VARCHAR or boolean worth_staying for API / frontend."""
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in ("yes", "true", "1"):
            return True
        if lowered in ("no", "false", "0"):
            return False
    return None


def normalize_easter_egg(egg: Any) -> Any:
    """Expose title/description and a detail alias for the existing frontend."""
    if not isinstance(egg, dict):
        return egg
    title = egg.get("title") or ""
    description = egg.get("description") or ""
    detail = egg.get("detail") or description or title
    return {
        "title": title or detail,
        "description": description or detail,
        "detail": detail,
        "significance": egg.get("significance"),
        "timestampMinutes": egg.get("timestamp_minutes")
        or egg.get("timestampMinutes"),
    }


def normalize_easter_eggs(eggs: Any) -> List[Any]:
    if not eggs:
        return []
    if isinstance(eggs, str):
        return []
    if not isinstance(eggs, list):
        return []
    return [normalize_easter_egg(egg) for egg in eggs]


MOVIES_COMPLETE_VIEW_SQL = """
CREATE OR REPLACE VIEW movies_complete AS
SELECT
    m.id,
    m.title,
    m.year,
    m.release_date,
    m.runtime_minutes,
    m.poster_path,
    m.overview,
    m.vote_average,
    m.popularity,
    m.tier,
    m.imdb_id,
    m.updated_at,
    pc.has_scene,
    pc.scene_count,
    pc.mid_credits,
    pc.post_credits AS post_credits_desc,
    pc.worth_staying,
    pc.spoiler_free_hint,
    pc.source_confidence,
    ri.reddit_discussion_count,
    ri.scraped_at AS reddit_scraped_at,
    (
        SELECT json_agg(json_build_object(
            'title', ee.title,
            'description', ee.description,
            'significance', ee.significance,
            'timestamp_minutes', ee.timestamp_minutes
        ))
        FROM easter_eggs ee
        WHERE ee.movie_id = m.id
    ) AS easter_eggs
FROM movies m
LEFT JOIN post_credits pc ON m.id = pc.movie_id
LEFT JOIN reddit_insights ri ON m.id = ri.movie_id
"""

BATCH_LOGS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS batch_logs (
    id SERIAL PRIMARY KEY,
    tier VARCHAR(50),
    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP,
    movies_processed INTEGER DEFAULT 0,
    movies_failed INTEGER DEFAULT 0,
    status VARCHAR(50) DEFAULT 'running'
)
"""
