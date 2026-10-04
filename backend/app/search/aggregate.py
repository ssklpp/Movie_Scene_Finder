"""영화 단위 집계 (SPEC §7.4).

    score(m) = s1 + W_SECOND_SCENE * s2 + W_PLOT * p_m
    m이 soft_filters를 하나 이상 만족하면 score(m) *= SOFT_FILTER_BOOST

s1, s2 = 그 영화 장면의 RRF 점수 1·2위(없으면 0), p_m = 줄거리 검색 RRF 점수(없으면 0).
상위 MOVIE_TOPK편과 영화별 근거 장면 최대 3개를 돌려준다.
"""

from collections import defaultdict
from collections.abc import Mapping, Sequence

from pydantic import BaseModel

from app.core.config import get_settings
from app.search.filters import MovieAttrs, matches_any
from app.search.hybrid import PlotHit, SceneHit

EVIDENCE_PER_MOVIE = 3


class MovieCandidate(BaseModel):
    movie_id: int
    score: float
    s1: float
    s2: float
    plot_score: float
    boosted: bool
    attrs: MovieAttrs
    evidence: list[SceneHit]


def aggregate(
    scene_hits: Sequence[SceneHit],
    plot_hits: Sequence[PlotHit],
    soft_filters: Mapping[str, str] | None = None,
    *,
    w_second_scene: float | None = None,
    w_plot: float | None = None,
    soft_filter_boost: float | None = None,
    movie_topk: int | None = None,
) -> list[MovieCandidate]:
    """가중치를 주지 않으면 설정(.env) 값을 쓴다. 점수가 같으면 movie_id 순."""
    s = get_settings()
    w2 = s.w_second_scene if w_second_scene is None else w_second_scene
    wp = s.w_plot if w_plot is None else w_plot
    boost = s.soft_filter_boost if soft_filter_boost is None else soft_filter_boost
    topk = s.movie_topk if movie_topk is None else movie_topk

    scenes_by_movie: dict[int, list[SceneHit]] = defaultdict(list)
    for hit in scene_hits:
        scenes_by_movie[hit.movie_id].append(hit)
    plots = {p.movie_id: p for p in plot_hits}

    candidates = []
    for movie_id in scenes_by_movie.keys() | plots.keys():
        scenes = sorted(scenes_by_movie.get(movie_id, []), key=lambda h: -h.score)
        s1 = scenes[0].score if scenes else 0.0
        s2 = scenes[1].score if len(scenes) > 1 else 0.0
        plot = plots.get(movie_id)
        p_m = plot.score if plot else 0.0
        attrs = scenes[0].attrs if scenes else plot.attrs if plot else MovieAttrs()
        score = s1 + w2 * s2 + wp * p_m
        boosted = matches_any(attrs, soft_filters)
        if boosted:
            score *= boost
        candidates.append(
            MovieCandidate(
                movie_id=movie_id,
                score=score,
                s1=s1,
                s2=s2,
                plot_score=p_m,
                boosted=boosted,
                attrs=attrs,
                evidence=scenes[:EVIDENCE_PER_MOVIE],
            )
        )
    candidates.sort(key=lambda c: (-c.score, c.movie_id))
    return candidates[:topk]
