from pathlib import Path
from typing import Any

import httpx
import pytest

from pipeline.common.http import get_json
from pipeline.common.state import State
from pipeline.s01_collect_meta import merge_candidates, to_movie_row

PARASITE: dict[str, Any] = {
    "id": 496243,
    "title": "기생충",
    "original_title": "기생충",
    "original_language": "ko",
    "origin_country": ["KR"],
    "release_date": "2019-05-30",
    "genres": [{"id": 35, "name": "코미디"}, {"id": 53, "name": "스릴러"}],
    "overview": "전원백수로 살 길 막막하지만 사이는 좋은 기택 가족.",
    "poster_path": "/abc.jpg",
    "translations": {
        "translations": [
            {"iso_639_1": "fr", "data": {"title": "Parasite (fr)"}},
            {"iso_639_1": "en", "data": {"title": "Parasite"}},
        ]
    },
}


def test_to_movie_row() -> None:
    row = to_movie_row(PARASITE)
    assert row == {
        "tmdb_id": 496243,
        "title_ko": "기생충",
        "title_en": "Parasite",
        "year": 2019,
        "country": "KR",
        "genres": ["코미디", "스릴러"],
        "is_animation": False,
        "plot_ko": "전원백수로 살 길 막막하지만 사이는 좋은 기택 가족.",
        "poster_url": "https://image.tmdb.org/t/p/w500/abc.jpg",
    }


def test_to_movie_row_fallbacks() -> None:
    detail: dict[str, Any] = {
        "id": 1,
        "title": "",
        "original_title": "Toy Story",
        "original_language": "en",
        "origin_country": [],
        "production_countries": [{"iso_3166_1": "US"}],
        "release_date": "",
        "genres": [{"id": 16, "name": "애니메이션"}],
        "overview": "",
        "poster_path": None,
    }
    row = to_movie_row(detail)
    assert row["title_ko"] is None
    assert row["title_en"] == "Toy Story"
    assert row["country"] == "US"
    assert row["year"] is None
    assert row["is_animation"] is True
    assert row["plot_ko"] is None
    assert row["poster_url"] is None


def test_merge_candidates_dedup_and_total() -> None:
    merged = merge_candidates([5, 6], [1, 5, 2, 3, 4], total=4)
    assert sorted(merged) == [1, 2, 5, 6]


def test_merge_candidates_keeps_kr_ratio_in_every_prefix() -> None:
    kr = list(range(1000, 1060))
    global_ids = list(range(1, 400))
    merged = merge_candidates(kr, global_ids, total=300)
    assert len(merged) == len(set(merged)) == 300
    assert set(kr) <= set(merged)
    for n in (10, 20, 100, 300):
        kr_in_prefix = sum(1 for i in merged[:n] if i >= 1000)
        assert kr_in_prefix == round(n * 60 / 300)


def test_state_roundtrip(tmp_path: Path) -> None:
    state = State(tmp_path / "state.sqlite")
    assert not state.is_done("s01", "1")
    state.mark_done("s01", "1")
    assert state.is_done("s01", "1")
    assert not state.is_done("s01", "1", model_version="v2")
    state.close()


def _client(statuses: list[int]) -> tuple[httpx.Client, list[int]]:
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        status = statuses[min(len(calls) - 1, len(statuses) - 1)]
        return httpx.Response(status, json={"ok": True})

    return httpx.Client(transport=httpx.MockTransport(handler), base_url="http://t"), calls


def test_get_json_retries_then_succeeds() -> None:
    client, calls = _client([429, 503, 200])
    assert get_json(client, "/x", backoff_s=0) == {"ok": True}
    assert len(calls) == 3


def test_get_json_gives_up_after_max_retries() -> None:
    client, calls = _client([500])
    with pytest.raises(httpx.HTTPStatusError):
        get_json(client, "/x", max_retries=3, backoff_s=0)
    assert len(calls) == 4


def test_get_json_does_not_retry_client_error() -> None:
    client, calls = _client([404])
    with pytest.raises(httpx.HTTPStatusError):
        get_json(client, "/x", backoff_s=0)
    assert len(calls) == 1
