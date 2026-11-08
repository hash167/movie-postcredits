from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    openai_api_key: str = ""
    tmdb_api_key: str
    database_url: str

    # S3-compatible storage. Values come from movie-api-secrets / movie-api-config
    # (S3_ENDPOINT, S3_ACCESS_KEY, S3_SECRET_KEY). No credential defaults.
    s3_endpoint: str = ""
    s3_bucket: str = "movies"
    s3_access_key: str = ""
    s3_secret_key: str = ""
    s3_region: str = "us-east-1"
    s3_public_url: str = ""

    export_dir: str = "./exports"
    # OLLAMA_HOST is set by the existing deployment config. Empty disables the default.
    ollama_host: str = ""
    ollama_model: str = "llama3.1:8b"

    class Config:
        env_file = ".env"


settings = Settings()
