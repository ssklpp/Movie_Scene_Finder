from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# gpt-6-luna가 받는 값("minimal"은 거부한다)
ReasoningEffort = Literal["none", "low", "medium", "high"]

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
    # local: vLLM(LOCAL_VLM_*), openai: LLM_MODEL_DEFAULT 실시간 호출,
    # openai_batch: Batch API(미구현)
    caption_backend: Literal["local", "openai", "openai_batch"] = "local"
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
    # 버킷 공개 주소(r2.dev 또는 연결한 도메인). backend는 이것만 있으면 thumb_url을 채운다.
    r2_public_url: str = ""

    # Search / agent
    confidence_threshold: float = 0.7
    max_clarify_turns: int = 2
    scene_topk: int = 50
    movie_topk: int = 10
    w_second_scene: float = 0.3
    w_plot: float = 0.5
    soft_filter_boost: float = 1.1
    # 에이전트 LLM 호출의 추론 강도. 둘 다 none(E6 비교: 품질 차이 없고 지연시간 꼬리가 사라짐).
    rewrite_reasoning_effort: ReasoningEffort = "none"
    verify_reasoning_effort: ReasoningEffort = "none"

    # Ops
    rate_limit_per_day: int = 30
    # 브라우저에서 API를 부를 수 있는 프런트엔드 주소(JSON 배열). 배포 시 Vercel 도메인을 더한다.
    cors_origins: list[str] = ["http://localhost:3000"]
    # 추적은 서버(와 평가에서 켰을 때)만 한다(core/tracing.py). 키가 없으면 켜지지 않는다.
    langsmith_tracing: bool = False
    langsmith_api_key: str = ""
    langsmith_project: str = "movie-scene-finder"

    # External API calls (SPEC §0.4)
    http_timeout_s: float = 30.0
    http_max_retries: int = 3

    @field_validator("database_url")
    @classmethod
    def use_psycopg_driver(cls, url: str) -> str:
        """Railway 등은 postgres:// 또는 postgresql:// 형식을 준다. SQLAlchemy가 설치된
        psycopg(3) 드라이버를 쓰도록 postgresql+psycopg://로 바꾼다."""
        for prefix in ("postgres://", "postgresql://"):
            if url.startswith(prefix):
                return "postgresql+psycopg://" + url[len(prefix) :]
        return url


@lru_cache
def get_settings() -> Settings:
    return Settings()
