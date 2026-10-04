from pathlib import Path

from PIL import Image, ImageDraw

from pipeline.s03_dedup import hamming, phash, pick_representatives


def test_hamming() -> None:
    assert hamming(0b1010, 0b1010) == 0
    assert hamming(0b1010, 0b0101) == 4
    assert hamming(0, (1 << 64) - 1) == 64


def test_pick_representatives_keeps_first_of_each_group() -> None:
    a = 0
    a_near = 0b111  # a와 거리 3
    b = (1 << 64) - 1
    b_near = b ^ 0b1111_1111  # b와 거리 8 (경계값, 같은 묶음)
    c = (1 << 32) - 1  # a, b와 거리 32
    hashes = [(0, a), (1, b), (2, a_near), (3, b_near), (4, c)]
    assert pick_representatives(hashes, max_distance=8) == [0, 1, 4]


def test_pick_representatives_distance_just_over_threshold_is_new_group() -> None:
    a = 0
    nine_bits = (1 << 9) - 1
    assert pick_representatives([(0, a), (1, nine_bits)], max_distance=8) == [0, 1]


def _image(path: Path, size: tuple[int, int], shape: str) -> Path:
    img = Image.new("RGB", (640, 360), "white")
    draw = ImageDraw.Draw(img)
    if shape == "box":
        draw.rectangle((100, 80, 300, 280), fill="black")
    else:
        draw.ellipse((350, 50, 600, 300), fill="black")
        draw.line((0, 360, 640, 0), fill="black", width=20)
    img.resize(size).save(path, "JPEG", quality=70)
    return path


def test_phash_resized_copy_is_near_and_different_image_is_far(tmp_path: Path) -> None:
    original = phash(_image(tmp_path / "a.jpg", (640, 360), "box"))
    resized = phash(_image(tmp_path / "b.jpg", (320, 180), "box"))
    other = phash(_image(tmp_path / "c.jpg", (640, 360), "circle"))
    assert hamming(original, resized) <= 8
    assert hamming(original, other) > 8
