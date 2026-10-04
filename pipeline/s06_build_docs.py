"""s06: 장면마다 검색 문서를 만들어 `pipeline/data/search_docs.jsonl`에 쓴다 (SPEC §6).

검색 문서 = caption_ko + setting + objects + 장르·연대. 영화 제목은 넣지 않는다. 화면 속 글자
(text_in_frame)도 제목 로고가 들어 있을 수 있어 넣지 않는다.

계산만 하는 단계라 매번 파일 전체를 새로 쓴다(같은 입력이면 같은 결과). s07이 이 파일을 읽는다.
"""

import argparse
import json
import logging
from collections.abc import Sequence
from typing import Any

from sqlalchemy import select

from app.core.config import REPO_ROOT, get_settings
from app.core.logging import setup_logging
from app.db.models import Movie, Scene
from app.db.session import SessionLocal
from pipeline.s04_caption import backend_config

logger = logging.getLogger(__name__)

SEARCH_DOCS_PATH = REPO_ROOT / "pipeline" / "data" / "search_docs.jsonl"


def decade_label(year: int | None) -> str | None:
    """2019 → "2010년대"."""
    return f"{year // 10 * 10}년대" if year else None


def build_search_text(
    caption_ko: str, tags: dict[str, Any], genres: Sequence[str] | None, year: int | None
) -> str:
    parts = [caption_ko.strip()]
    if setting := (tags.get("setting") or "").strip():
        parts.append(f"장소: {setting}")
    if objects := [o.strip() for o in tags.get("objects") or [] if o.strip()]:
        parts.append(f"물건: {', '.join(objects)}")
    if genres:
        parts.append(f"장르: {', '.join(genres)}")
    if decade := decade_label(year):
        parts.append(f"연대: {decade}")
    return "\n".join(parts)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, help="movies 앞 N편의 장면만 (s01과 같은 순서)")
    args = parser.parse_args()
    setup_logging()

    model_version = backend_config(get_settings()).model_version
    with SessionLocal() as session:
        movie_ids = select(Movie.id).order_by(Movie.id).limit(args.limit).scalar_subquery()
        stmt = (
            select(
                Scene.id,
                Scene.movie_id,
                Movie.tmdb_id,
                Scene.caption_ko,
                Scene.tags,
                Scene.model_version,
                Movie.genres,
                Movie.year,
            )
            .join(Movie, Scene.movie_id == Movie.id)
            .where(Movie.id.in_(movie_ids))
            .order_by(Scene.movie_id, Scene.id)
        )
        rows = session.execute(stmt).all()

    written = skipped = 0
    SEARCH_DOCS_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = SEARCH_DOCS_PATH.with_suffix(".part")
    with tmp.open("w", encoding="utf-8") as f:
        for scene_id, movie_id, tmdb_id, caption_ko, tags, version, genres, year in rows:
            if not caption_ko or tags is None or version != model_version:
                skipped += 1
                continue
            doc = {
                "scene_id": scene_id,
                "movie_id": movie_id,
                "tmdb_id": tmdb_id,
                "model_version": version,
                "search_text": build_search_text(caption_ko, tags, genres, year),
            }
            f.write(json.dumps(doc, ensure_ascii=False) + "\n")
            written += 1
    tmp.replace(SEARCH_DOCS_PATH)
    logger.info(
        "s06 done: %d docs, %d skipped (no caption or model_version != %s) -> %s",
        written,
        skipped,
        model_version,
        SEARCH_DOCS_PATH,
    )


if __name__ == "__main__":
    main()
