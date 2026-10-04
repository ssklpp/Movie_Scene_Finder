"""Kiwi 사용자 사전을 영화 제목과 인물명으로 만든다 (SPEC §7.2).

사전 파일은 `backend/app/search/data/user_dict.txt`다. 배포된 backend도 질의 토큰화에 써야 해서
저장소에 포함한다. 사전을 바꾸면 s07(sparse)을 다시 돌리고 s08로 다시 적재해야 검색이 맞는다.

인물은 영화별 주요 배우와 감독의 한글 이름이다(TMDB credits, ko-KR). Kiwi 사용자 단어에는 공백을
넣을 수 없어서, 띄어 쓴 이름은 두 글자 이상인 부분만 넣고 띄어 쓴 제목은 넣지 않는다. 제목을
나누면 "제왕의" 같은 일반 단어까지 고유명사로 등록되기 때문이다.
"""

import argparse
import json
import logging
import re
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from sqlalchemy import select

from app.core.config import REPO_ROOT, get_settings
from app.core.logging import setup_logging
from app.db.models import Movie
from app.db.session import SessionLocal
from app.search.sparse import USER_DICT_PATH  # backend 질의 토큰화와 같은 파일
from pipeline.common.tmdb import TmdbClient

logger = logging.getLogger(__name__)

DATA_DIR = REPO_ROOT / "pipeline" / "data"
CREDITS_DIR = DATA_DIR / "credits"
TOP_CAST = 10
HANGUL_WORD = re.compile(r"^[가-힣]{2,}$")


def title_words(title: str | None) -> list[str]:
    """띄어쓰기 없는 한글 제목만 한 단어로 넣는다. 문장부호와 숫자가 섞이면 넣지 않는다."""
    if title and HANGUL_WORD.match(title):
        return [title]
    return []


def name_words(name: str) -> list[str]:
    """한글 이름을 공백으로 나눠 두 글자 이상인 부분만 넣는다. 가운뎃점(·) 등도 구분자로 본다."""
    return [part for part in re.split(r"[\s·・.\-]+", name) if HANGUL_WORD.match(part)]


def credit_names(credits: dict[str, Any], top_cast: int = TOP_CAST) -> list[str]:
    cast = sorted(credits.get("cast", []), key=lambda m: m.get("order", 0))[:top_cast]
    directors = [m for m in credits.get("crew", []) if m.get("job") == "Director"]
    return [m["name"] for m in [*cast, *directors] if m.get("name")]


def build_entries(titles: Iterable[str | None], names: Iterable[str]) -> list[str]:
    words = {w for t in titles for w in title_words(t)} | {w for n in names for w in name_words(n)}
    return [f"{w}\tNNP" for w in sorted(words)]


def load_credits(tmdb: TmdbClient, tmdb_id: int, force: bool) -> dict[str, Any]:
    path = CREDITS_DIR / f"{tmdb_id}.json"
    if path.exists() and not force:
        cached: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        return cached
    credits = tmdb.movie_credits(tmdb_id)
    path.write_text(json.dumps(credits, ensure_ascii=False), encoding="utf-8")
    return credits


def write_user_dict(entries: list[str], path: Path = USER_DICT_PATH) -> None:
    path.write_text("\n".join(entries) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, help="movies 앞 N편만 처리 (s01과 같은 순서)")
    parser.add_argument("--force", action="store_true", help="저장된 credits를 무시하고 다시 받음")
    args = parser.parse_args()
    setup_logging()
    logging.getLogger("httpx").setLevel(logging.WARNING)

    with SessionLocal() as session:
        stmt = select(Movie.tmdb_id, Movie.title_ko).order_by(Movie.id).limit(args.limit)
        movies = list(session.execute(stmt).all())

    CREDITS_DIR.mkdir(parents=True, exist_ok=True)
    settings = get_settings()
    tmdb = TmdbClient(settings.tmdb_read_token, settings.http_timeout_s)
    names: list[str] = []
    try:
        for tmdb_id, _ in movies:
            names.extend(credit_names(load_credits(tmdb, tmdb_id, args.force)))
    finally:
        tmdb.close()

    entries = build_entries([title for _, title in movies], names)
    write_user_dict(entries)
    logger.info(
        "user dict: %d entries from %d movies -> %s", len(entries), len(movies), USER_DICT_PATH
    )


if __name__ == "__main__":
    main()
