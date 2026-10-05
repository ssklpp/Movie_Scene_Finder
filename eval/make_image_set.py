"""이미지 평가 세트 (SPEC §11 image: 원본 스틸 크롭·색 변경·모니터 촬영, dev 50 / test 50).

- 캡션이 있는 장면이 있는 영화에서 고정 시드로 100편을 고르고, 영화마다 장면 하나를 쓴다.
- 앞 80개는 자동 변형이다. 변형 4종(crop, color, crop_color, degrade)을 20개씩 돌려 쓴다.
  결과는 eval/data/images/img-XXXX.jpg.
- 뒤 20개는 모니터 촬영용이다. 원본을 eval/data/to_shoot/img-XXXX.jpg로 내보낸다. 사람이 이
  원본을 모니터에 띄워 휴대폰으로 찍고, 사진을 eval/data/photos/img-XXXX.jpg(.jpeg/.png)로
  넣는다. 사진이 있는 것만 데이터셋에 들어가므로 사진을 넣은 뒤 다시 실행한다.
- 촬영 사진(휴대폰 원본 5712x3213, 장당 3~4.5MB)은 긴 변 2048px, JPEG 품질 90으로 줄여
  eval/data/images/에 쓴다. OpenAI 비전 입력도 2048px 안으로 줄인 뒤 짧은 변 768px로 맞추므로
  모델이 보는 정보는 같고, 서비스 업로드 한도(5MB)에 들어오는 크기가 된다.
- split은 번호 순으로 dev/test를 번갈아 준다(자동 40/40, 촬영 10/10).
- 이미지는 TMDB 저작물이라 git에 넣지 않는다(eval/data/). 데이터셋 jsonl만 저장소에 둔다.
  같은 시드·같은 DB면 같은 장면과 같은 변형이 다시 만들어진다.

    uv run python -m eval.make_image_set
"""

import argparse
import json
import logging
import random
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageEnhance, ImageFilter, ImageOps
from sqlalchemy import select

from app.core.config import REPO_ROOT
from app.core.logging import setup_logging
from app.db.models import Movie, Scene
from app.db.session import SessionLocal
from pipeline.s02_collect_images import image_path

logger = logging.getLogger(__name__)

VERSION = "v1"
OUT_PATH = REPO_ROOT / "eval" / "datasets" / f"image_{VERSION}.jsonl"
DATA_DIR = REPO_ROOT / "eval" / "data"
IMAGES_DIR = DATA_DIR / "images"
TO_SHOOT_DIR = DATA_DIR / "to_shoot"
PHOTOS_DIR = DATA_DIR / "photos"  # 촬영 원본
N_AUTO = 80
N_MONITOR = 20
TRANSFORMS = ("crop", "color", "crop_color", "degrade")
PHOTO_SUFFIXES = (".jpg", ".jpeg", ".png")
PHOTO_MAX_SIDE = 2048
PHOTO_QUALITY = 90


@dataclass(frozen=True)
class Pick:
    id: str
    scene_id: str
    movie_id: int
    tmdb_id: int
    kind: str  # TRANSFORMS 중 하나 또는 "monitor"
    split: str


def source_path(scene_id: str) -> Path:
    """ "{tmdb_id}_backdrop_{n}" → s02가 받은 원본 경로."""
    tmdb_id, _, n = scene_id.split("_")
    return image_path(int(tmdb_id), int(n))


def pick_scenes(
    scenes_by_movie: dict[tuple[int, int], list[str]], seed: int, n_auto: int, n_monitor: int
) -> list[Pick]:
    """(movie_id, tmdb_id)별 장면 목록에서 영화 n_auto + n_monitor편을 골라 장면 하나씩."""
    rng = random.Random(seed)
    movies = sorted(scenes_by_movie)
    chosen = rng.sample(movies, n_auto + n_monitor)
    picks = []
    for i, (movie_id, tmdb_id) in enumerate(chosen):
        scene_id = rng.choice(sorted(scenes_by_movie[(movie_id, tmdb_id)]))
        kind = TRANSFORMS[i % len(TRANSFORMS)] if i < n_auto else "monitor"
        split = "dev" if i % 2 == 0 else "test"
        picks.append(Pick(f"img-{i + 1:04d}", scene_id, movie_id, tmdb_id, kind, split))
    return picks


def random_crop(img: Image.Image, rng: random.Random) -> Image.Image:
    """가로세로 각각 45~70%를 무작위 위치에서 잘라 낸다(화면 일부만 기억하는 경우)."""
    w, h = img.size
    cw, ch = round(w * rng.uniform(0.45, 0.7)), round(h * rng.uniform(0.45, 0.7))
    x, y = rng.randint(0, w - cw), rng.randint(0, h - ch)
    return img.crop((x, y, x + cw, y + ch))


def recolor(img: Image.Image, rng: random.Random) -> Image.Image:
    """흑백 또는 색조 이동 + 채도·밝기 변경(화면·필터마다 색이 다르게 보이는 경우)."""
    if rng.random() < 0.25:
        return ImageOps.grayscale(img).convert("RGB")
    shift = rng.choice([-1, 1]) * rng.randint(15, 40)
    h, s, v = img.convert("HSV").split()
    h = h.point(lambda x: (x + shift) % 256)
    out = Image.merge("HSV", (h, s, v)).convert("RGB")
    out = ImageEnhance.Color(out).enhance(rng.uniform(0.5, 1.5))
    return ImageEnhance.Brightness(out).enhance(rng.uniform(0.7, 1.3))


def degrade(img: Image.Image, rng: random.Random) -> Image.Image:
    """작게 줄였다 키우고 흐리게, 조금 기울여 가장자리를 잘라 낸다(저화질 캡처)."""
    w, h = img.size
    small = img.resize((max(w // 4, 1), max(h // 4, 1)), Image.Resampling.BILINEAR)
    out = small.resize((w, h), Image.Resampling.BILINEAR).filter(ImageFilter.GaussianBlur(1.5))
    out = out.rotate(rng.uniform(-5, 5), resample=Image.Resampling.BILINEAR)
    m = round(min(w, h) * 0.08)  # 회전으로 생긴 검은 모서리를 잘라 낸다
    return out.crop((m, m, w - m, h - m))


def transform(img: Image.Image, kind: str, rng: random.Random) -> tuple[Image.Image, int]:
    """(변형한 이미지, JPEG 품질)."""
    img = img.convert("RGB")
    if kind == "crop":
        return random_crop(img, rng), 90
    if kind == "color":
        return recolor(img, rng), 90
    if kind == "crop_color":
        return recolor(random_crop(img, rng), rng), 35
    if kind == "degrade":
        return degrade(img, rng), 50
    raise ValueError(f"unknown transform: {kind}")


def photo_path(pick_id: str, photos_dir: Path = PHOTOS_DIR) -> Path | None:
    for suffix in PHOTO_SUFFIXES:
        path = photos_dir / f"{pick_id}{suffix}"
        if path.exists():
            return path
    return None


def shrink_photo(img: Image.Image, max_side: int = PHOTO_MAX_SIDE) -> Image.Image:
    """EXIF 방향대로 세우고 긴 변을 max_side 이하로 줄인다(작으면 그대로)."""
    out = ImageOps.exif_transpose(img).convert("RGB")
    out.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()
    setup_logging()

    with SessionLocal() as session:
        rows = session.execute(
            select(Scene.id, Movie.id, Movie.tmdb_id)
            .join(Movie, Scene.movie_id == Movie.id)
            .where(Scene.caption_ko.is_not(None))
        ).all()
    scenes_by_movie: dict[tuple[int, int], list[str]] = defaultdict(list)
    for scene_id, movie_id, tmdb_id in rows:
        scenes_by_movie[(movie_id, tmdb_id)].append(scene_id)
    picks = pick_scenes(scenes_by_movie, args.seed, N_AUTO, N_MONITOR)

    IMAGES_DIR.mkdir(parents=True, exist_ok=True)
    TO_SHOOT_DIR.mkdir(parents=True, exist_ok=True)
    records = []
    missing_photos = []
    for p in picks:
        src = source_path(p.scene_id)
        if p.kind == "monitor":
            shoot = TO_SHOOT_DIR / f"{p.id}.jpg"
            if not shoot.exists():
                shoot.write_bytes(src.read_bytes())
            photo = photo_path(p.id)
            if photo is None:
                missing_photos.append(p.id)
                continue
            path = IMAGES_DIR / f"{p.id}.jpg"
            with Image.open(photo) as img:
                shrink_photo(img).save(path, "JPEG", quality=PHOTO_QUALITY)
        else:
            path = IMAGES_DIR / f"{p.id}.jpg"
            rng = random.Random(f"{args.seed}:{p.id}")
            with Image.open(src) as img:
                out, quality = transform(img, p.kind, rng)
            out.save(path, "JPEG", quality=quality)
        records.append(
            {
                "id": p.id,
                "query": None,
                "image_path": path.relative_to(REPO_ROOT).as_posix(),
                "answer_movie_id": p.movie_id,
                "answer_tmdb_id": p.tmdb_id,
                "source": "image",
                "split": p.split,
                "version": VERSION,
                "scene_id": p.scene_id,
                "transform": p.kind,
            }
        )
    OUT_PATH.write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records), encoding="utf-8"
    )
    by_split = {s: sum(r["split"] == s for r in records) for s in ("dev", "test")}
    logger.info("wrote %d records %s -> %s", len(records), by_split, OUT_PATH.name)
    if missing_photos:
        logger.info(
            "monitor photos missing (%d): shoot %s/<id>.jpg and save as %s/<id>.jpg: %s",
            len(missing_photos),
            TO_SHOOT_DIR.relative_to(REPO_ROOT),
            PHOTOS_DIR.relative_to(REPO_ROOT),
            ", ".join(missing_photos),
        )


if __name__ == "__main__":
    main()
