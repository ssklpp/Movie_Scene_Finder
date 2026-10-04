"""s02: 영화별 TMDB backdrop을 최대 15장 받아 `pipeline/data/images/{tmdb_id}/`에 저장한다.

TMDB 영화에는 still이 없어서(still은 TV 에피소드용) backdrop만 쓴다. 글자 없는 backdrop을 먼저
고른다. 제목 로고가 박힌 이미지는 캡션의 text_in_frame으로 제목이 검색 문서에 섞일 수 있다.
"""

import argparse
import logging
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import select

from app.core.config import REPO_ROOT, get_settings
from app.core.logging import setup_logging
from app.db.models import Movie
from app.db.session import SessionLocal
from pipeline.common.state import State
from pipeline.common.tmdb import TmdbClient

logger = logging.getLogger(__name__)

STEP = "s02"
SOURCE = "backdrop"
IMAGES_DIR = REPO_ROOT / "pipeline" / "data" / "images"
TEXTLESS_LANGS = {None, "xx"}


def select_backdrops(backdrops: list[dict[str, Any]], max_count: int) -> list[str]:
    """글자 없는 backdrop을 먼저, 그다음 글자 있는 것. 각 그룹 안에서는 TMDB 순서를 유지한다."""
    textless = [b for b in backdrops if b.get("iso_639_1") in TEXTLESS_LANGS]
    texted = [b for b in backdrops if b.get("iso_639_1") not in TEXTLESS_LANGS]
    return [b["file_path"] for b in [*textless, *texted][:max_count]]


def image_path(tmdb_id: int, n: int) -> Path:
    return IMAGES_DIR / str(tmdb_id) / f"{SOURCE}_{n:02d}.jpg"


def download_one(tmdb: TmdbClient, file_path: str, dest: Path, size: str) -> None:
    if dest.exists():
        return
    tmp = dest.with_suffix(".part")
    tmp.write_bytes(tmdb.download_image(file_path, size))
    tmp.rename(dest)


def collect_movie(
    tmdb: TmdbClient, pool: ThreadPoolExecutor, tmdb_id: int, max_images: int, size: str
) -> tuple[int, int]:
    """(받은 이미지 수, 실패 수). 실패한 이미지는 건너뛰고 다음 실행에서 다시 받는다."""
    file_paths = select_backdrops(tmdb.movie_images(tmdb_id).get("backdrops", []), max_images)
    (IMAGES_DIR / str(tmdb_id)).mkdir(parents=True, exist_ok=True)
    futures = [
        (fp, pool.submit(download_one, tmdb, fp, image_path(tmdb_id, n), size))
        for n, fp in enumerate(file_paths)
    ]
    failed = 0
    for fp, f in futures:
        try:
            f.result()
        except httpx.HTTPError as e:
            logger.warning("movie %d: image %s failed after retries: %s", tmdb_id, fp, e)
            failed += 1
    return len(file_paths) - failed, failed


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, help="movies 앞 N편만 처리 (s01과 같은 순서)")
    parser.add_argument("--force", action="store_true", help="이미 처리한 영화도 목록을 다시 받음")
    parser.add_argument("--max-images", type=int, default=15, help="영화당 최대 이미지 수")
    parser.add_argument("--size", default="w1280", help="TMDB 이미지 크기 (w780, w1280, original)")
    parser.add_argument("--workers", type=int, default=8, help="동시 다운로드 수")
    parser.add_argument("--with-trailers", action="store_true", help="예고편 키프레임 추가")
    args = parser.parse_args()
    setup_logging()
    logging.getLogger("httpx").setLevel(logging.WARNING)

    if args.with_trailers:
        raise SystemExit("--with-trailers is not implemented yet")

    with SessionLocal() as session:
        stmt = select(Movie.tmdb_id).order_by(Movie.id).limit(args.limit)
        tmdb_ids = list(session.scalars(stmt))

    settings = get_settings()
    tmdb = TmdbClient(settings.tmdb_read_token, settings.http_timeout_s)
    state = State()
    processed = skipped = images = incomplete = 0
    try:
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            for i, tmdb_id in enumerate(tmdb_ids, 1):
                if not args.force and state.is_done(STEP, str(tmdb_id)):
                    skipped += 1
                    continue
                ok, failed = collect_movie(tmdb, pool, tmdb_id, args.max_images, args.size)
                images += ok
                if failed:
                    incomplete += 1
                else:
                    state.mark_done(STEP, str(tmdb_id))
                processed += 1
                if i % 20 == 0:
                    logger.info("progress %d/%d movies, %d images", i, len(tmdb_ids), images)
        logger.info(
            "s02 done: processed=%d skipped=%d images=%d incomplete_movies=%d (rerun to retry)",
            processed,
            skipped,
            images,
            incomplete,
        )
    finally:
        tmdb.close()
        state.close()


if __name__ == "__main__":
    main()
