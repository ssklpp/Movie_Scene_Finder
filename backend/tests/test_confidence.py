import pytest

from app.search.aggregate import MovieCandidate
from app.search.confidence import Verified, confidence, rerank
from app.search.filters import MovieAttrs


def cand(movie_id: int, score: float = 1.0) -> MovieCandidate:
    return MovieCandidate(
        movie_id=movie_id,
        score=score,
        s1=score,
        s2=0.0,
        plot_score=0.0,
        boosted=False,
        attrs=MovieAttrs(),
        evidence=[],
    )


def ver(movie_id: int, score: float) -> Verified:
    return Verified(movie_id=movie_id, score=score, reason="r", evidence_scene_ids=[])


@pytest.mark.parametrize(
    ("scores", "expected"),
    [
        ([0.9, 0.3], 0.6 * 0.9 + 0.4 * 1.0),  # 격차 0.6 ≥ 0.3 → 1로 잘림
        ([0.8, 0.7], 0.6 * 0.8 + 0.4 * (0.1 / 0.3)),
        ([0.5, 0.5], 0.6 * 0.5),  # 격차 0
        ([0.7], 0.6 * 0.7 + 0.4 * 1.0),  # 후보 하나 → v2 = 0
        ([], 0.0),
        ([1.4, -0.2], 0.6 * 1.0 + 0.4 * 1.0),  # 0~1로 자름
    ],
)
def test_confidence_spec_formula(scores: list[float], expected: float) -> None:
    assert confidence(scores) == pytest.approx(expected)


def test_confidence_threshold_examples() -> None:
    # 기본 임계값 0.7: 뚜렷한 1위는 통과, 접전은 재질문
    assert confidence([0.85, 0.4]) >= 0.7
    assert confidence([0.6, 0.55]) < 0.7


def test_rerank_by_verification_score() -> None:
    ranked = rerank(
        [cand(1, 0.9), cand(2, 0.8), cand(3, 0.7)], [ver(1, 0.2), ver(2, 0.9), ver(3, 0.5)]
    )
    assert [r.candidate.movie_id for r in ranked] == [2, 3, 1]
    assert [r.verified.score for r in ranked] == [0.9, 0.5, 0.2]


def test_rerank_missing_unknown_clamp_and_stable_ties() -> None:
    ranked = rerank(
        [cand(1), cand(2), cand(3)],
        [ver(3, 1.5), ver(99, 1.0), ver(1, 0.0)],  # 2는 빠짐, 99는 후보에 없음
    )
    assert [r.candidate.movie_id for r in ranked] == [3, 1, 2]  # 1과 2는 0점 동점 → 원래 순서
    assert ranked[0].verified.score == 1.0
    assert ranked[2].verified.reason == "" and ranked[2].verified.score == 0.0
