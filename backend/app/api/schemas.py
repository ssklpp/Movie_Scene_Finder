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
