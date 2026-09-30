from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    openai_api_key: str = ""
    tmdb_api_key: str = ""
    database_url: str = "postgresql://localhost/moviedb"

    # S3-Compatible Storage Configuration (MinIO, AWS S3, etc.)
    s3_endpoint: str = "http://localhost:9000"  # MinIO default
    s3_bucket: str = "movies"  # Bucket name
    s3_access_key: str = "minioadmin"  # Access key
    s3_secret_key: str = "minioadmin"  # Secret key
    s3_region: str = "us-east-1"  # Region
    s3_public_url: str = ""  # Optional: Custom public URL (e.g., CDN)

    export_dir: str = "./exports"
    ollama_host: str = "http://100.67.63.33:11434"
    ollama_model: str = "llama3.1:8b"

    class Config:
        env_file = ".env"


settings = Settings()
