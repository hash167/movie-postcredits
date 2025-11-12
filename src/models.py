from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime


class EasterEgg(BaseModel):
    detail: str
    significance: str
    confidence: str
    source_url: Optional[str] = None


class PostCreditsScene(BaseModel):
    has_scene: bool
    scene_count: int
    descriptions: List[str]
    worth_staying: Optional[bool]
    spoiler_free_hint: Optional[str]


class RedditInsights(BaseModel):
    easter_eggs: List[EasterEgg]
    post_credits: PostCreditsScene
    reddit_discussion_count: int
    community_rating: Optional[float] = None
    source_urls: List[str]


class EnhancedMovie(BaseModel):
    id: int
    title: str
    year: int
    release_date: Optional[str] = None
    runtime_minutes: int = 0
    poster_path: Optional[str] = None
    overview: str = ""
    vote_average: float = 0.0
    popularity: float = 0.0
    tier: str
    imdb_id: Optional[str] = None
    reddit_insights: Optional[RedditInsights] = None
    last_updated: datetime = datetime.now()
