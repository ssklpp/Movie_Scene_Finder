"""GET /movies/{id} (SPEC §9): 영화 상세와 장면(근거 후보). 썸네일 URL은 R2를 붙이는 Phase 5부터."""

from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from app.api.schemas import MovieDetail, SceneOut
from app.db.models import Movie, Scene
from app.db.session import SessionLocal

router = APIRouter()


@router.get("/movies/{movie_id}")
def get_movie(movie_id: int) -> MovieDetail:
    with SessionLocal() as db:
        movie = db.get(Movie, movie_id)
        if movie is None:
            raise HTTPException(404, "movie not found")
        scenes = db.scalars(select(Scene).where(Scene.movie_id == movie_id).order_by(Scene.id))
        return MovieDetail(
            movie_id=movie.id,
            tmdb_id=movie.tmdb_id,
            title_ko=movie.title_ko,
            title_en=movie.title_en,
            year=movie.year,
            country=movie.country,
            genres=movie.genres or [],
            is_animation=bool(movie.is_animation),
            plot_ko=movie.plot_ko,
            poster_url=movie.poster_url,
            scenes=[
                SceneOut(scene_id=s.id, thumb_url=None, caption_ko=s.caption_ko) for s in scenes
            ],
        )
