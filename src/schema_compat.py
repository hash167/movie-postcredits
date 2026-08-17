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
    """Map live title/description → {detail, significance} for the frontend."""
    if isinstance(egg, str):
        return {"detail": egg, "significance": None}
    if not isinstance(egg, dict):
        return egg
    description = egg.get("description") or ""
    title = egg.get("title") or ""
    # Live DB has description, not detail. Prefer description.
    detail = description or title or egg.get("detail") or ""
    return {
        "detail": detail,
        "significance": egg.get("significance"),
        "title": title or None,
        "description": description or None,
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
            'detail', COALESCE(ee.description, ee.title),
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

EXTRACT_JOBS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS extract_jobs (
    id SERIAL PRIMARY KEY,
    movie_id INT UNIQUE NOT NULL,
    title TEXT,
    year INT,
    status VARCHAR(20) DEFAULT 'queued',
    attempts INT DEFAULT 0,
    last_error TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    started_at TIMESTAMP,
    finished_at TIMESTAMP,
    locked_at TIMESTAMP
)
"""

# Claim lock is only held for this transaction. COMMIT before Ollama.
# 10 min stale timeout > Ollama 420s so a live job is not stolen;
# a crash leaves status=running until that timeout.
CLAIM_EXTRACT_JOB_SQL = """
SELECT id, movie_id, title, year, attempts
FROM extract_jobs
WHERE status = 'queued'
ORDER BY created_at
FOR UPDATE SKIP LOCKED
LIMIT 1
"""

MARK_EXTRACT_RUNNING_SQL = """
UPDATE extract_jobs
SET status = 'running',
    attempts = attempts + 1,
    started_at = $2,
    locked_at = $2
WHERE id = $1
RETURNING id, movie_id, title, year, attempts
"""

REQUEUE_STALE_RUNNING_SQL = """
UPDATE extract_jobs
SET status = 'queued'
WHERE status = 'running'
  AND started_at < $1
  AND attempts < 3
"""

FAIL_STALE_RUNNING_SQL = """
UPDATE extract_jobs
SET status = 'failed',
    finished_at = $2,
    last_error = COALESCE(last_error, 'stale running timeout')
WHERE status = 'running'
  AND started_at < $1
  AND attempts >= 3
"""
