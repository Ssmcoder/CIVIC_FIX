import os
from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "sqlite+aiosqlite:///./civicfix.db"
    secret_key: str = "dev-secret-change-me"
    access_token_expire_minutes: int = 60 * 8
    media_dir: str = "./media"
    media_max_mb: int = 25
    tracking_token_secret: str = "tracking-dev-secret"

    # Chatbot / LLM
    llm_provider: str = "ollama"  # "ollama" | "openai" | "rule"
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "llama3.2:3b"
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"

    # ML
    ml_model_dir: str = "../ml/models"
    embedding_backend: str = "auto"  # "auto" | "tfidf" | "sentence"
    dedup_auto_link_threshold: float = 0.82
    dedup_review_threshold: float = 0.62
    dedup_max_distance_m: float = 300.0
    dedup_time_window_days: int = 30
    classify_review_threshold: float = 0.55

    # Location
    default_lat: float = 20.2986   # Bhubaneswar
    default_lon: float = 85.8245

    cors_origins: str = "http://localhost:5173,http://localhost:3000"

    @property
    def media_path(self) -> str:
        p = os.path.abspath(self.media_dir)
        os.makedirs(p, exist_ok=True)
        return p


@lru_cache
def get_settings() -> Settings:
    return Settings()
