"""재질문 속성 선택 (SPEC §7.6). 속성은 코드가 엔트로피로 고른다.

질문 문장은 속성별 고정 문장(QUESTIONS)이다. SPEC은 질문 문장을 LLM이 만든다고 했지만,
그 호출이 재질문 요청마다 1.2~2.5초를 더해 지연시간 목표를 넘겨 고정 문장으로 바꿨다.
선택지는 버튼으로 따로 보여주므로 문장이 고정이어도 쓰는 데 지장이 적다.

- 후보 속성: decade, country(KR / other), genre(대표 장르 = TMDB 첫 번째 장르), is_animation
- 상위 5편에 대해 속성별로 검증 점수 가중 분포의 엔트로피(bit)를 구하고, 이미 물은 속성을
  뺀 최댓값을 고른다. 최대 엔트로피가 0이면 재질문하지 않는다.
- 선택지 = 가중치가 큰 값 최대 3개 + "unknown"(모르겠어요). "unknown"은 필터를 더하지 않는다.
- 값의 의미는 `search/filters.py`와 같다.
"""

import math
from collections import defaultdict
from collections.abc import Collection, Mapping, Sequence

from pydantic import BaseModel

from app.search.filters import COUNTRY_KR, COUNTRY_OTHER, FILTER_KEYS, MovieAttrs

TOP_N = 5
MAX_OPTIONS = 3
UNKNOWN = "unknown"

QUESTIONS = {
    "decade": "언제쯤 나온 영화였는지 기억나세요?",
    "country": "한국 영화였나요, 외국 영화였나요?",
    "genre": "어떤 장르에 가까운 영화였나요?",
    "is_animation": "애니메이션이었나요, 실사 영화였나요?",
}


class ClarifyOption(BaseModel):
    value: str  # 필터 값 또는 "unknown"
    label: str  # 화면에 보일 말


class ClarifyChoice(BaseModel):
    attr: str
    entropy: float
    options: list[ClarifyOption]


def attr_value(attrs: MovieAttrs, attr: str) -> str | None:
    """재질문용 속성 값. 알 수 없으면 None."""
    if attr == "decade":
        return attrs.decade
    if attr == "country":
        if attrs.country is None:
            return None
        return COUNTRY_KR if attrs.country == COUNTRY_KR else COUNTRY_OTHER
    if attr == "genre":
        return attrs.genres[0] if attrs.genres else None
    if attr == "is_animation":
        return "true" if attrs.is_animation else "false"
    raise ValueError(f"unknown attribute: {attr}")


def option_label(attr: str, value: str) -> str:
    if value == UNKNOWN:
        return "모르겠어요"
    if attr == "decade" and value.endswith("s") and value[:-1].isdigit():
        return f"{value[:-1]}년대"
    if attr == "country":
        return "한국 영화" if value == COUNTRY_KR else "외국 영화"
    if attr == "is_animation":
        return "애니메이션" if value == "true" else "실사 영화"
    return value


def weighted_distribution(items: Sequence[tuple[MovieAttrs, float]], attr: str) -> dict[str, float]:
    """값별 가중치 합(정규화 전). 값을 알 수 없는 영화는 뺀다.

    검증 점수가 모두 0이면 같은 가중치(1)로 센다.
    """
    use_uniform = all(w <= 0 for _, w in items)
    dist: dict[str, float] = defaultdict(float)
    for attrs, weight in items:
        value = attr_value(attrs, attr)
        if value is not None:
            dist[value] += 1.0 if use_uniform else max(weight, 0.0)
    return {k: v for k, v in dist.items() if v > 0}


def entropy(weights: Mapping[str, float]) -> float:
    total = sum(weights.values())
    if total <= 0:
        return 0.0
    return -sum((w / total) * math.log2(w / total) for w in weights.values() if w > 0)


def choose_attribute(
    items: Sequence[tuple[MovieAttrs, float]],
    asked: Collection[str] = (),
    top_n: int = TOP_N,
) -> ClarifyChoice | None:
    """(영화 속성, 검증 점수) 목록(검증 점수 순)에서 물을 속성을 고른다. 물을 게 없으면 None.

    엔트로피가 같으면 FILTER_KEYS 순서(decade, country, genre, is_animation)로 앞선 것을 고른다.
    """
    top = list(items)[:top_n]
    best: ClarifyChoice | None = None
    for attr in FILTER_KEYS:
        if attr in asked:
            continue
        dist = weighted_distribution(top, attr)
        h = entropy(dist)
        if h <= 1e-9 or (best is not None and h <= best.entropy + 1e-12):
            continue
        values = sorted(dist, key=lambda v: (-dist[v], v))[:MAX_OPTIONS]
        options = [ClarifyOption(value=v, label=option_label(attr, v)) for v in values]
        options.append(ClarifyOption(value=UNKNOWN, label=option_label(attr, UNKNOWN)))
        best = ClarifyChoice(attr=attr, entropy=h, options=options)
    return best


def apply_answer(hard_filters: Mapping[str, str], attr: str, value: str) -> dict[str, str]:
    """재질문 답을 hard_filters에 더한 새 dict. "unknown"이면 그대로."""
    if attr not in FILTER_KEYS:
        raise ValueError(f"unknown attribute: {attr}")
    updated = dict(hard_filters)
    if value != UNKNOWN:
        updated[attr] = value
    return updated
