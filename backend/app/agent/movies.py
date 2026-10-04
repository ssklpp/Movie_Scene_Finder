"""에이전트가 쓰는 영화 메타데이터(제목·연도·포스터)와 장르 목록. 300편이라 한 번 읽어 둔다."""

from functools import lru_cache

from pydantic import BaseModel
from sqlalchemy import select

from app.db.models import Movie
from app.db.session import SessionLocal


class MovieInfo(BaseModel):
    movie_id: int
    tmdb_id: int
    title_ko: str | None
    title_en: str | None
    year: int | None
    poster_url: str | None
    genres: list[str]


@lru_cache
def all_movies() -> dict[int, MovieInfo]:
    with SessionLocal() as session:
        return {
            m.id: MovieInfo(
                movie_id=m.id,
                tmdb_id=m.tmdb_id,
                title_ko=m.title_ko,
                title_en=m.title_en,
                year=m.year,
                poster_url=m.poster_url,
                genres=m.genres or [],
            )
            for m in session.scalars(select(Movie))
        }


def movie_info(movie_id: int) -> MovieInfo | None:
    return all_movies().get(movie_id)


def known_genres() -> list[str]:
    """색인된 영화의 장르(TMDB 한국어 장르명)."""
    return sorted({g for m in all_movies().values() for g in m.genres})
