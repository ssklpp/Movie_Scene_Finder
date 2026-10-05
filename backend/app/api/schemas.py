from datetime import datetime

from pydantic import BaseModel


class AnswerRequest(BaseModel):
    value: str


class FeedbackRequest(BaseModel):
    session_id: str
    movie_id: int
    is_correct: bool


class SceneOut(BaseModel):
    scene_id: str
    thumb_url: str | None
    caption_ko: str | None


class MovieDetail(BaseModel):
    movie_id: int
    tmdb_id: int
    title_ko: str | None
    title_en: str | None
    year: int | None
    country: str | None
    genres: list[str]
    is_animation: bool
    plot_ko: str | None
    poster_url: str | None
    scenes: list[SceneOut]


class EvalRunOut(BaseModel):
    id: int
    experiment: str
    name: str
    split: str
    dataset_version: str | None
    agent: bool
    recall_at_1: float | None
    recall_at_5: float | None
    mrr: float | None
    clarify_success: float | None
    avg_clarify: float | None
    p95_latency_ms: int | None
    cost_per_query_usd: float | None
    commit: str | None
    created_at: datetime
