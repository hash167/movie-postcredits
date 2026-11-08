"""Set non-secret defaults before src.config.Settings is constructed."""
import os

os.environ.setdefault("TMDB_API_KEY", "test-only-not-a-real-key")
os.environ.setdefault("DATABASE_URL", "postgresql://movieuser@localhost:5432/moviedb")
os.environ.setdefault("OLLAMA_HOST", "http://127.0.0.1:9")
os.environ.setdefault("S3_ENDPOINT", "http://127.0.0.1:9")
os.environ.setdefault("S3_ACCESS_KEY", "test-only")
os.environ.setdefault("S3_SECRET_KEY", "test-only")
