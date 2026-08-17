"""Postgres extract job queue helpers (no Redis/Kafka)."""

from datetime import datetime, timedelta
from typing import Any, Dict, Optional

STALE_AFTER = timedelta(minutes=10)
MAX_ATTEMPTS = 3


def movie_has_eggs_or_credits(movie: Optional[Dict[str, Any]]) -> bool:
    if not movie:
        return False
    eggs = movie.get("easter_eggs") or []
    if isinstance(eggs, str):
        eggs = eggs.strip()
        has_eggs = bool(eggs) and eggs not in ("[]", "null")
    else:
        has_eggs = isinstance(eggs, list) and len(eggs) > 0
    has_credits = bool(movie.get("has_scene"))
    return has_eggs or has_credits


def enqueue_decision(existing: Optional[Dict[str, Any]], has_content: bool) -> str:
    """Return insert | noop | requeue."""
    if existing is None:
        return "insert"
    status = (existing.get("status") or "").lower()
    if status in ("queued", "running"):
        return "noop"
    if status == "done" and not has_content:
        return "requeue"
    if status == "failed":
        return "requeue"
    return "noop"


def status_after_error(attempts: int) -> str:
    return "queued" if attempts < MAX_ATTEMPTS else "failed"


def stale_running_action(started_at: Optional[datetime], attempts: int, now: datetime) -> Optional[str]:
    if started_at is None:
        return None
    if now - started_at < STALE_AFTER:
        return None
    if attempts < MAX_ATTEMPTS:
        return "queued"
    return "failed"
