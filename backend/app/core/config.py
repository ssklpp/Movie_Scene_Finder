from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=REPO_ROOT / ".env", env_file_encoding="utf-8", extra="ignore"
    )

    # OpenAI
    openai_api_key: str = ""
    llm_model_default: str = ""
    llm_model_strong: str = ""
    embed_model: str = ""
    embed_dim: int = 1536
    model_prices_usd_per_1m: dict[str, tuple[float, float]] = {}

    # Caption backend
    caption_backend: Literal["local", "openai_batch"] = "local"
    local_vlm_base_url: str = "http://localhost:8001/v1"
    local_vlm_model: str = ""
    caption_model_version: str = ""

    # Data sources
    tmdb_read_token: str = ""
    kmdb_api_key: str = ""

    # Storage
    database_url: str = "postgresql+psycopg://app:app@localhost:5432/msf"
    qdrant_url: str = "http://localhost:6333"
    qdrant_api_key: str = ""
    qdrant_scenes_alias: str = "scenes"
    r2_account_id: str = ""
    r2_access_key_id: str = ""
    r2_secret_access_key: str = ""
    r2_bucket: str = "msf-thumbs"

    # Search / agent
    confidence_threshold: float = 0.7
    max_clarify_turns: int = 2
    scene_topk: int = 50
    movie_topk: int = 10
    w_second_scene: float = 0.3
    w_plot: float = 0.5
    soft_filter_boost: float = 1.1

    # Ops
    rate_limit_per_day: int = 30
    langsmith_api_key: str = ""
    langsmith_project: str = "movie-scene-finder"

    # External API calls (SPEC §0.4)
    http_timeout_s: float = 30.0
    http_max_retries: int = 3


@lru_cache
def get_settings() -> Settings:
    return Settings()
