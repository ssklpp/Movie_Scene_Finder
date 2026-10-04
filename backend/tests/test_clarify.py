import math

import pytest

from app.search.clarify import (
    FALLBACK_QUESTIONS,
    UNKNOWN,
    apply_answer,
    attr_value,
    choose_attribute,
    entropy,
    option_label,
    weighted_distribution,
)
from app.search.filters import FILTER_KEYS, MovieAttrs


def movie(
    decade: str | None = "2010s",
    country: str | None = "US",
    genres: list[str] | None = None,
    anim: bool = False,
) -> MovieAttrs:
    return MovieAttrs(decade=decade, country=country, genres=genres or ["액션"], is_animation=anim)


def test_attr_value() -> None:
    m = movie(decade="2000s", country="JP", genres=["애니메이션", "가족"], anim=True)
    assert attr_value(m, "decade") == "2000s"
    assert attr_value(m, "country") == "other"
    assert attr_value(movie(country="KR"), "country") == "KR"
    assert attr_value(m, "genre") == "애니메이션"  # 대표 장르 = 첫 번째
    assert attr_value(m, "is_animation") == "true"
    assert attr_value(MovieAttrs(), "decade") is None
    assert attr_value(MovieAttrs(), "country") is None
    assert attr_value(MovieAttrs(), "genre") is None
    with pytest.raises(ValueError):
        attr_value(m, "director")


def test_entropy_bits() -> None:
    assert entropy({"a": 1.0}) == 0.0
    assert entropy({"a": 1.0, "b": 1.0}) == pytest.approx(1.0)
    assert entropy({"a": 1, "b": 1, "c": 1, "d": 1}) == pytest.approx(2.0)
    assert entropy({}) == 0.0
    p = 0.9
    assert entropy({"a": p, "b": 1 - p}) == pytest.approx(
        -(p * math.log2(p) + (1 - p) * math.log2(1 - p))
    )


def test_weighted_distribution_skips_unknown_values_and_uniform_when_all_zero() -> None:
    items = [(movie(decade="2010s"), 0.6), (movie(decade=None), 0.9), (movie(decade="2000s"), 0.2)]
    assert weighted_distribution(items, "decade") == {"2010s": 0.6, "2000s": 0.2}
    zero = [(movie(decade="2010s"), 0.0), (movie(decade="2000s"), 0.0)]
    assert weighted_distribution(zero, "decade") == {"2010s": 1.0, "2000s": 1.0}


def test_choose_attribute_picks_max_entropy() -> None:
    # 연대는 반반(1 bit), 국가는 모두 같음(0), 장르는 한쪽으로 치우침
    items = [
        (movie(decade="2010s", genres=["액션"]), 0.5),
        (movie(decade="2000s", genres=["액션"]), 0.5),
        (movie(decade="2010s", genres=["드라마"]), 0.1),
        (movie(decade="2000s", genres=["액션"]), 0.1),
    ]
    choice = choose_attribute(items)
    assert choice is not None and choice.attr == "decade"
    assert choice.entropy == pytest.approx(1.0)
    assert [o.value for o in choice.options] == ["2000s", "2010s", UNKNOWN]
    assert [o.label for o in choice.options] == ["2000년대", "2010년대", "모르겠어요"]


def test_choose_attribute_excludes_asked_and_uses_top5_only() -> None:
    items = [(movie(decade=d, country=c), 1.0) for d, c in [("2010s", "KR"), ("2000s", "US")]]
    items += [(movie(genres=[g]), 1.0) for g in ["드라마", "코미디", "공포", "SF"]]  # 6위는 무시
    choice = choose_attribute(items, asked={"decade", "genre"})
    assert choice is not None and choice.attr == "country"
    assert {o.value for o in choice.options} == {"KR", "other", UNKNOWN}
    assert choose_attribute(items, asked=set(FILTER_KEYS)) is None


def test_choose_attribute_none_when_all_entropy_zero() -> None:
    same = [(movie(), 0.9), (movie(), 0.3)]
    assert choose_attribute(same) is None


def test_options_capped_at_three_by_weight() -> None:
    items = [
        (movie(decade=f"{y}s"), w) for y, w in [(1990, 0.1), (2000, 0.4), (2010, 0.3), (2020, 0.2)]
    ]
    choice = choose_attribute(items, asked={"genre", "country", "is_animation"})
    assert choice is not None
    assert [o.value for o in choice.options] == ["2000s", "2010s", "2020s", UNKNOWN]


def test_ties_prefer_spec_attribute_order() -> None:
    # 연대와 국가가 모두 1 bit → decade가 먼저
    items = [(movie(decade="2010s", country="KR"), 1.0), (movie(decade="2000s", country="US"), 1.0)]
    choice = choose_attribute(items)
    assert choice is not None and choice.attr == "decade"


def test_option_labels() -> None:
    assert option_label("country", "KR") == "한국 영화"
    assert option_label("country", "other") == "외국 영화"
    assert option_label("is_animation", "true") == "애니메이션"
    assert option_label("is_animation", "false") == "실사 영화"
    assert option_label("genre", "스릴러") == "스릴러"


def test_apply_answer() -> None:
    base = {"country": "KR"}
    assert apply_answer(base, "decade", "2010s") == {"country": "KR", "decade": "2010s"}
    assert apply_answer(base, "decade", UNKNOWN) == base
    assert base == {"country": "KR"}  # 원본은 바뀌지 않는다
    with pytest.raises(ValueError):
        apply_answer(base, "director", "x")


def test_fallback_question_for_every_attribute() -> None:
    assert set(FALLBACK_QUESTIONS) == set(FILTER_KEYS)
