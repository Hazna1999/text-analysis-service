from pydantic_settings import BaseSettings
from pydantic import ConfigDict


class Settings(BaseSettings):
    database_url: str
    redis_url: str
    third_party_api_url: str
    third_party_api_key: str
    max_concurrent_requests: int = 10
    max_retries: int = 5
    chunk_size: int = 50

    model_config = ConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

settings = Settings()