"""s03: 영화별 이미지의 pHash로 거의 같은 이미지를 묶어 묶음마다 대표 1장을 `scenes`에 넣는다.

같은 영화 안에서 해밍 거리 ≤ 20이면 같은 묶음이다. 이미지를 s02 순서(글자 없는 것 우선,
TMDB 순)로 보면서 기존 대표와 가까우면 버리고 아니면 새 대표로 고른다. 캡션은 비워 둔다(s04).

기준값은 SPEC의 8 대신 20이다. TMDB backdrop에는 같은 이미지를 자르거나 확대하거나 색·배경만
바꾼 사본이 많은데, 거리 10~20 표본이 모두 이런 사본이었다. 8로는 4,446장 중 204장만 걸러졌다.
"""

import argparse
import logging
import re
from pathlib import Path

import imagehash
from PIL import Image
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert

from app.core.logging import setup_logging
from app.db.models import Movie, Scene
from app.db.session import SessionLocal
from pipeline.common.state import State
from pipeline.s02_collect_images import IMAGES_DIR, SOURCE

logger = logging.getLogger(__name__)

STEP = "s03"
IMAGE_NAME = re.compile(rf"^{SOURCE}_(\d+)\.jpg$")


def hamming(a: int, b: int) -> int:
    return (a ^ b).bit_count()


def pick_representatives(hashes: list[tuple[int, int]], max_distance: int) -> list[int]:
    """(n, hash) 목록을 순서대로 보면서 기존 대표와 거리가 `max_distance` 이하인 것은 버린다.

    남은 대표의 n 목록을 원래 순서대로 돌려준다.
    """
    reps: list[tuple[int, int]] = []
    for n, h in hashes:
        if all(hamming(h, rh) > max_distance for _, rh in reps):
            reps.append((n, h))
    return [n for n, _ in reps]


def list_images(tmdb_id: int) -> list[tuple[int, Path]]:
    movie_dir = IMAGES_DIR / str(tmdb_id)
    if not movie_dir.is_dir():
        return []
    found = []
    for p in movie_dir.iterdir():
        m = IMAGE_NAME.match(p.name)
        if m:
            found.append((int(m.group(1)), p))
    return sorted(found)


def phash(path: Path) -> int:
    with Image.open(path) as img:
        return int(str(imagehash.phash(img)), 16)


def scene_id(tmdb_id: int, n: int) -> str:
    return f"{tmdb_id}_{SOURCE}_{n}"


def dedup_movie(movie_id: int, tmdb_id: int, max_distance: int) -> tuple[int, int]:
    """(이미지 수, 대표 수)를 돌려준다.

    대표가 아닌 기존 scenes 행은 지우고, 대표 행은 캡션을 보존한 채 upsert한다.
    """
    hashes = [(n, phash(p)) for n, p in list_images(tmdb_id)]
    by_n = dict(hashes)
    reps = pick_representatives(hashes, max_distance)
    rows = [
        {
            "id": scene_id(tmdb_id, n),
            "movie_id": movie_id,
            "source": SOURCE,
            "phash": f"{by_n[n]:016x}",
        }
        for n in reps
    ]
    with SessionLocal.begin() as session:
        session.execute(
            delete(Scene).where(
                Scene.movie_id == movie_id,
                Scene.source == SOURCE,
                Scene.id.not_in([r["id"] for r in rows]),
            )
        )
        if rows:
            stmt = insert(Scene).values(rows)
            stmt = stmt.on_conflict_do_update(
                index_elements=[Scene.id], set_={"phash": stmt.excluded.phash}
            )
            session.execute(stmt)
    return len(hashes), len(reps)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, help="movies 앞 N편만 처리 (s01과 같은 순서)")
    parser.add_argument("--force", action="store_true", help="이미 처리한 영화도 다시 계산")
    parser.add_argument("--max-distance", type=int, default=20, help="같은 묶음으로 볼 해밍 거리")
    args = parser.parse_args()
    setup_logging()

    with SessionLocal() as session:
        stmt = select(Movie.id, Movie.tmdb_id).order_by(Movie.id).limit(args.limit)
        movies = list(session.execute(stmt).tuples())

    state = State()
    processed = skipped = images = scenes = 0
    try:
        for i, (movie_id, tmdb_id) in enumerate(movies, 1):
            if not args.force and state.is_done(STEP, str(tmdb_id)):
                skipped += 1
                continue
            n_images, n_reps = dedup_movie(movie_id, tmdb_id, args.max_distance)
            if n_images == 0:
                logger.warning("movie %d has no images; run s02 first", tmdb_id)
                continue
            images += n_images
            scenes += n_reps
            state.mark_done(STEP, str(tmdb_id))
            processed += 1
            if i % 50 == 0:
                logger.info("progress %d/%d movies", i, len(movies))
        logger.info(
            "s03 done: processed=%d skipped=%d images=%d scenes=%d",
            processed,
            skipped,
            images,
            scenes,
        )
    finally:
        state.close()


if __name__ == "__main__":
    main()
