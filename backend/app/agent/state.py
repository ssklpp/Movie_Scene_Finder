"""에이전트 상태 (SPEC §8.1).

상태 안의 pydantic 모델은 체크포인터(PostgresSaver)가 직렬화한다. 새 모델을 상태에 넣으면
STATE_MODELS에도 추가해야 재개할 때 복원된다(checkpoint.make_serde).
"""

import operator
from collections.abc import Mapping
from typing import Annotated, Literal, TypedDict

from pydantic import BaseModel

from app.search.aggregate import MovieCandidate
from app.search.caption import People, SceneCaption
from app.search.clarify import ClarifyChoice, ClarifyOption
from app.search.confidence import Verified
from app.search.filters import MovieAttrs
from app.search.hybrid import PlotHit, SceneHit


class Rewritten(BaseModel):
    """질의 재작성 결과 (SPEC §7.1). soft_filters는 사용자가 확신 없이 말한 조건이다."""

    scene_ko: str
    keywords_ko: list[str]
    soft_filters: dict[Literal["country", "decade", "genre", "is_animation"], str]


class Question(BaseModel):
    attr: str
    text: str
    options: list[ClarifyOption]


class EvidenceScene(BaseModel):
    scene_id: str
    thumb_url: str | None
    caption_ko: str


class ResultItem(BaseModel):
    movie_id: int
    title_ko: str | None
    year: int | None
    poster_url: str | None
    score: float
    reason: str
    evidence: list[EvidenceScene]


def sum_timings(left: Mapping[str, int], right: Mapping[str, int]) -> dict[str, int]:
    """노드별 소요 시간을 더한다(재질문으로 같은 노드가 여러 번 돌 수 있다)."""
    merged = dict(left)
    for k, v in right.items():
        merged[k] = merged.get(k, 0) + v
    return merged


class SearchState(TypedDict, total=False):
    session_id: str
    query_text: str | None
    image_key: str | None
    image_caption: SceneCaption | None
    rewritten: Rewritten | None
    hard_filters: dict[str, str]
    asked_attrs: list[str]
    scene_hits: list[SceneHit]
    plot_hits: list[PlotHit]
    movie_candidates: list[MovieCandidate]
    verified: list[Verified]
    confidence: float
    clarify_choice: ClarifyChoice | None  # verify가 고른 재질문 속성(없으면 답한다)
    clarify_turns: int
    pending_question: Question | None
    result: list[ResultItem] | None
    cost_usd: Annotated[float, operator.add]  # 노드는 이번에 쓴 비용만 돌려준다
    timings_ms: Annotated[dict[str, int], sum_timings]


# 체크포인트에서 복원을 허용할 모델(상태에 들어가는 모든 pydantic 모델)
STATE_MODELS: list[type[BaseModel]] = [
    Rewritten,
    Question,
    EvidenceScene,
    ResultItem,
    SceneCaption,
    People,
    SceneHit,
    PlotHit,
    MovieAttrs,
    MovieCandidate,
    Verified,
    ClarifyChoice,
    ClarifyOption,
]
