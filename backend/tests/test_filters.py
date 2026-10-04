import pytest
from qdrant_client import models as qm

from app.search.filters import MovieAttrs, matches, matches_any, to_qdrant_filter

PARASITE = MovieAttrs(year=2019, decade="2010s", country="KR", genres=["코미디", "스릴러"])
TOY_STORY = MovieAttrs(
    year=1995, decade="1990s", country="US", genres=["애니메이션"], is_animation=True
)


def test_from_payload_ignores_none_and_extra_fields() -> None:
    attrs = MovieAttrs.from_payload(
        {"year": 2019, "decade": "2010s", "country": None, "genres": ["드라마"], "scene_id": "x"}
    )
    assert attrs == MovieAttrs(year=2019, decade="2010s", genres=["드라마"])
    assert MovieAttrs.from_payload(None) == MovieAttrs()


def test_to_qdrant_filter_empty_is_none() -> None:
    assert to_qdrant_filter(None) is None
    assert to_qdrant_filter({}) is None


def test_to_qdrant_filter_conditions() -> None:
    f = to_qdrant_filter({"decade": "2010s", "genre": "액션", "is_animation": "false"})
    assert f is not None and f.must_not is None
    assert f.must == [
        qm.FieldCondition(key="decade", match=qm.MatchValue(value="2010s")),
        qm.FieldCondition(key="genres", match=qm.MatchValue(value="액션")),
        qm.FieldCondition(key="is_animation", match=qm.MatchValue(value=False)),
    ]


def test_to_qdrant_filter_country_other_is_must_not_kr() -> None:
    f = to_qdrant_filter({"country": "other"})
    assert f is not None and f.must is None
    assert f.must_not == [qm.FieldCondition(key="country", match=qm.MatchValue(value="KR"))]
    kr = to_qdrant_filter({"country": "KR"})
    assert kr is not None and kr.must == f.must_not


@pytest.mark.parametrize(
    ("key", "value", "parasite", "toy_story"),
    [
        ("decade", "2010s", True, False),
        ("country", "KR", True, False),
        ("country", "other", False, True),
        ("genre", "스릴러", True, False),
        ("is_animation", "true", False, True),
        ("is_animation", "false", True, False),
    ],
)
def test_matches(key: str, value: str, parasite: bool, toy_story: bool) -> None:
    assert matches(PARASITE, key, value) is parasite
    assert matches(TOY_STORY, key, value) is toy_story


def test_country_other_requires_known_country() -> None:
    assert not matches(MovieAttrs(country=None), "country", "other")


def test_unknown_key_raises() -> None:
    with pytest.raises(ValueError):
        matches(PARASITE, "director", "봉준호")
    with pytest.raises(ValueError):
        to_qdrant_filter({"director": "봉준호"})


def test_matches_any() -> None:
    assert matches_any(PARASITE, {"decade": "1990s", "country": "KR"})
    assert not matches_any(PARASITE, {"decade": "1990s"})
    assert not matches_any(PARASITE, None)
