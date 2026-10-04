import pytest

from app.db.models import Movie
from app.search.qdrant import decade_key
from pipeline.common.retry import retry
from pipeline.s08_upload import batches, movie_payload, next_version, point_id, stale_versions


def test_decade_key_matches_clarify_option_format() -> None:
    assert decade_key(2019) == "2010s"
    assert decade_key(2000) == "2000s"
    assert decade_key(None) is None


def test_point_id_is_deterministic_uuid() -> None:
    assert point_id("496243_backdrop_0") == point_id("496243_backdrop_0")
    assert point_id("496243_backdrop_0") != point_id("496243_backdrop_1")
    assert len(point_id("x")) == 36


def test_next_version_ignores_other_collections() -> None:
    assert next_version([]) == 1
    assert next_version(["movies", "scenes_v1", "scenes_v3", "scenes_vx", "scenes"]) == 4


def test_stale_versions_keeps_latest() -> None:
    names = ["scenes_v10", "scenes_v2", "movies", "scenes_v9"]
    assert stale_versions(names, keep=2) == ["scenes_v2"]
    assert stale_versions(names, keep=5) == []


def test_batches() -> None:
    assert [list(b) for b in batches([1, 2, 3, 4, 5], 2)] == [[1, 2], [3, 4], [5]]


def test_movie_payload_filter_fields() -> None:
    movie = Movie(
        id=7, tmdb_id=496243, year=2019, country="KR", genres=["코미디"], is_animation=None
    )
    assert movie_payload(movie) == {
        "movie_id": 7,
        "tmdb_id": 496243,
        "year": 2019,
        "decade": "2010s",
        "country": "KR",
        "genres": ["코미디"],
        "is_animation": False,
    }


def test_retry_succeeds_after_failures_and_gives_up() -> None:
    calls = {"n": 0}

    def flaky() -> str:
        calls["n"] += 1
        if calls["n"] < 3:
            raise ConnectionError("down")
        return "ok"

    assert retry(flaky, "flaky", backoff_s=0) == "ok"
    assert calls["n"] == 3

    def always_fail() -> None:
        raise ConnectionError("down")

    with pytest.raises(ConnectionError):
        retry(always_fail, "fail", max_retries=2, backoff_s=0)
