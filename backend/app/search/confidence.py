"""검증 결과로 후보를 재정렬하고 확신도를 계산한다 (SPEC §7.5).

검증 자체(LLM_MODEL_DEFAULT 구조화 출력)는 에이전트 verify 노드가 한다. 여기서는
    confidence = 0.6 * v1 + 0.4 * min(1, (v1 - v2) / 0.3)
v1, v2 = 검증 점수 1·2위(후보가 하나면 v2 = 0).
"""

from collections.abc import Sequence

from pydantic import BaseModel

from app.search.aggregate import MovieCandidate

GAP_SCALE = 0.3


class Verified(BaseModel):
    """LLM이 영화 하나에 대해 돌려주는 검증 결과."""

    movie_id: int
    score: float  # 0~1
    reason: str
    evidence_scene_ids: list[str]


class VerifyOutput(BaseModel):
    """verify 노드의 구조화 출력 스키마."""

    items: list[Verified]


class RankedCandidate(BaseModel):
    candidate: MovieCandidate
    verified: Verified


def clamp01(x: float) -> float:
    return min(max(x, 0.0), 1.0)


def rerank(
    candidates: Sequence[MovieCandidate], verified: Sequence[Verified]
) -> list[RankedCandidate]:
    """검증 점수 순으로 재정렬한다.

    LLM이 빠뜨린 후보는 0점, 후보에 없는 movie_id는 무시, 점수는 0~1로 자른다.
    점수가 같으면 원래(집계) 순서를 유지한다.
    """
    by_id = {v.movie_id: v for v in verified}
    ranked = []
    for c in candidates:
        v = by_id.get(c.movie_id)
        if v is None:
            v = Verified(movie_id=c.movie_id, score=0.0, reason="", evidence_scene_ids=[])
        else:
            v = v.model_copy(update={"score": clamp01(v.score)})
        ranked.append(RankedCandidate(candidate=c, verified=v))
    # sorted는 안정 정렬이므로 동점이면 집계 순서가 유지된다.
    return sorted(ranked, key=lambda r: -r.verified.score)


def confidence(scores: Sequence[float]) -> float:
    """내림차순 검증 점수로 확신도를 계산한다. 후보가 없으면 0."""
    if not scores:
        return 0.0
    v1 = clamp01(scores[0])
    v2 = clamp01(scores[1]) if len(scores) > 1 else 0.0
    gap = max(v1 - v2, 0.0)
    return 0.6 * v1 + 0.4 * min(1.0, gap / GAP_SCALE)
