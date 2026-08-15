"""Dummy settings so src.config can import without a real .env."""

import os

os.environ.setdefault("OPENAI_API_KEY", "test-openai-key")
os.environ.setdefault("TMDB_API_KEY", "test-tmdb-key")
os.environ.setdefault(
    "DATABASE_URL", "postgresql://test:test@localhost:5432/testdb"
)
