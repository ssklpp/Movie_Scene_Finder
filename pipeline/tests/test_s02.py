from typing import Any

from pipeline.s02_collect_images import select_backdrops


def test_select_backdrops_textless_first_then_texted() -> None:
    backdrops: list[dict[str, Any]] = [
        {"file_path": "/en1.jpg", "iso_639_1": "en"},
        {"file_path": "/none1.jpg", "iso_639_1": None},
        {"file_path": "/ko1.jpg", "iso_639_1": "ko"},
        {"file_path": "/xx1.jpg", "iso_639_1": "xx"},
        {"file_path": "/none2.jpg", "iso_639_1": None},
    ]
    assert select_backdrops(backdrops, 4) == ["/none1.jpg", "/xx1.jpg", "/none2.jpg", "/en1.jpg"]


def test_select_backdrops_fewer_than_max() -> None:
    assert select_backdrops([{"file_path": "/a.jpg", "iso_639_1": "en"}], 15) == ["/a.jpg"]
    assert select_backdrops([], 15) == []
