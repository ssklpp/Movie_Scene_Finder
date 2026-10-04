import pytest

from app.search.aggregate import MovieCandidate, aggregate
from app.search.filters import MovieAttrs
from app.search.hybrid import PlotHit, SceneHit

KR_2010 = MovieAttrs(year=2019, decade="2010s", country="KR", genres=["드라마"])
US_1990 = MovieAttrs(year=1995, decade="1990s", country="US", genres=["애니메이션"])


def agg(
    hits: list[SceneHit],
    plots: list[PlotHit],
    soft: dict[str, str] | None = None,
    topk: int = 10,
) -> list[MovieCandidate]:
    return aggregate(
        hits, plots, soft, w_second_scene=0.3, w_plot=0.5, soft_filter_boost=1.1, movie_topk=topk
    )


def scene(movie_id: int, n: int, score: float, attrs: MovieAttrs = KR_2010) -> SceneHit:
    return SceneHit(
        scene_id=f"{movie_id}_backdrop_{n}",
        movie_id=movie_id,
        score=score,
        caption_ko=f"장면 {n}",
        attrs=attrs,
    )


def test_spec_formula_s1_s2_plot() -> None:
    hits = [scene(1, 0, 0.5), scene(1, 1, 0.25), scene(1, 2, 0.1)]
    plots = [PlotHit(movie_id=1, score=0.4, attrs=KR_2010)]
    [m] = agg(hits, plots)
    assert (m.s1, m.s2, m.plot_score) == (0.5, 0.25, 0.4)
    assert m.score == pytest.approx(0.5 + 0.3 * 0.25 + 0.5 * 0.4)
    assert not m.boosted


def test_missing_second_scene_and_plot_are_zero() -> None:
    [m] = agg([scene(1, 0, 0.5)], [])
    assert (m.s2, m.plot_score, m.score) == (0.0, 0.0, 0.5)


def test_plot_only_movie_is_candidate_with_plot_attrs() -> None:
    [m] = agg([], [PlotHit(movie_id=2, score=0.5, attrs=US_1990)])
    assert m.movie_id == 2 and m.s1 == 0.0 and m.evidence == []
    assert m.score == pytest.approx(0.5 * 0.5)
    assert m.attrs == US_1990


def test_soft_filter_boost_applies_once_when_any_matches() -> None:
    hits = [scene(1, 0, 0.5, KR_2010), scene(2, 0, 0.5, US_1990)]
    result = agg(hits, [], {"country": "KR", "decade": "2010s"})
    by_id = {m.movie_id: m for m in result}
    assert by_id[1].boosted and by_id[1].score == pytest.approx(0.5 * 1.1)
    assert not by_id[2].boosted and by_id[2].score == pytest.approx(0.5)
    assert [m.movie_id for m in result] == [1, 2]


def test_ranking_topk_and_tie_break_by_movie_id() -> None:
    hits = [scene(3, 0, 0.2), scene(2, 0, 0.5), scene(1, 0, 0.5), scene(4, 0, 0.1)]
    result = agg(hits, [], topk=3)
    assert [m.movie_id for m in result] == [1, 2, 3]


def test_evidence_is_top3_scenes_by_score() -> None:
    hits = [scene(1, n, s) for n, s in enumerate([0.1, 0.5, 0.2, 0.3, 0.05])]
    [m] = agg(hits, [])
    assert [h.scene_id for h in m.evidence] == ["1_backdrop_1", "1_backdrop_3", "1_backdrop_2"]
    assert (m.s1, m.s2) == (0.5, 0.3)


def test_defaults_come_from_settings() -> None:
    [m] = aggregate([scene(1, 0, 0.5), scene(1, 1, 0.5)], [])
    assert m.score > 0.5  # W_SECOND_SCENE 기본값(0.3)이 적용된다
