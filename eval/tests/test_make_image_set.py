import random
from pathlib import Path

from PIL import Image

from eval.make_image_set import (
    TRANSFORMS,
    photo_path,
    pick_scenes,
    shrink_photo,
    source_path,
    transform,
)


def _scenes(n_movies: int) -> dict[tuple[int, int], list[str]]:
    return {(m, 1000 + m): [f"{1000 + m}_backdrop_{k}" for k in range(3)] for m in range(n_movies)}


def test_pick_scenes_is_deterministic_and_splits_evenly() -> None:
    picks = pick_scenes(_scenes(150), seed=0, n_auto=80, n_monitor=20)
    assert picks == pick_scenes(_scenes(150), seed=0, n_auto=80, n_monitor=20)
    assert len(picks) == 100
    assert len({p.movie_id for p in picks}) == 100  # 영화마다 한 장
    auto, monitor = picks[:80], picks[80:]
    assert {p.kind for p in monitor} == {"monitor"}
    for kind in TRANSFORMS:
        assert sum(p.kind == kind for p in auto) == 20
    # 변형 종류마다 dev/test가 반씩(종류가 한쪽 split에 몰리지 않게)
    for kind in (*TRANSFORMS, "monitor"):
        same = [p for p in picks if p.kind == kind]
        assert sum(p.split == "dev" for p in same) == len(same) // 2
    assert picks[0].id == "img-0001" and picks[-1].id == "img-0100"
    for p in picks:
        assert p.scene_id.startswith(f"{p.tmdb_id}_")


def test_source_path() -> None:
    path = source_path("985939_backdrop_9")
    assert path.parts[-2:] == ("985939", "backdrop_09.jpg")


def test_transforms_change_image() -> None:
    img = Image.new("RGB", (400, 200), (200, 50, 50))
    for kind in TRANSFORMS:
        out, quality = transform(img, kind, random.Random(0))
        assert out.mode == "RGB" and 0 < quality <= 90
        assert out.size != img.size or out.getpixel((10, 10)) != img.getpixel((10, 10))


def test_photo_path_accepts_jpeg_and_png(tmp_path: Path) -> None:
    assert photo_path("img-0081", tmp_path) is None
    (tmp_path / "img-0081.png").write_bytes(b"x")
    assert photo_path("img-0081", tmp_path) == tmp_path / "img-0081.png"


def test_shrink_photo_caps_long_side() -> None:
    big = Image.new("RGB", (5712, 3213))
    assert shrink_photo(big).size == (2048, 1152)
    small = Image.new("RGB", (800, 600))
    assert shrink_photo(small).size == (800, 600)
