"""검색 필터 값의 의미 (SPEC §7.1, §7.6). hard_filters(Qdrant 필터)와 soft_filters(점수 boost)가
같은 의미를 쓰도록 한곳에 둔다.

| 키 | 값 | 의미 |
| --- | --- | --- |
| decade | "2010s" | payload decade가 같다 |
| country | "KR" / "other" | 한국 영화 / 한국 외 (SPEC: KR / 기타) |
| genre | "액션" | payload genres(TMDB 한국어 장르명)에 들어 있다 |
| is_animation | "true" / "false" | 애니메이션 여부 |
"""

from collections.abc import Mapping

from pydantic import BaseModel
from qdrant_client import models as qm

FILTER_KEYS = ("decade", "country", "genre", "is_animation")
COUNTRY_KR = "KR"
COUNTRY_OTHER = "other"


class MovieAttrs(BaseModel):
    """필터·재질문에 쓰는 영화 속성 (Qdrant payload와 같은 이름)."""

    year: int | None = None
    decade: str | None = None
    country: str | None = None
    genres: list[str] = []
    is_animation: bool = False

    @classmethod
    def from_payload(cls, payload: Mapping[str, object] | None) -> "MovieAttrs":
        return cls.model_validate({k: v for k, v in (payload or {}).items() if v is not None})


def _condition(key: str, value: str) -> tuple[list[qm.Condition], list[qm.Condition]]:
    """(must, must_not) 조건."""
    if key == "decade":
        return [qm.FieldCondition(key="decade", match=qm.MatchValue(value=value))], []
    if key == "country":
        kr = qm.FieldCondition(key="country", match=qm.MatchValue(value=COUNTRY_KR))
        if value == COUNTRY_OTHER:
            return [], [kr]
        return [qm.FieldCondition(key="country", match=qm.MatchValue(value=value))], []
    if key == "genre":
        return [qm.FieldCondition(key="genres", match=qm.MatchValue(value=value))], []
    if key == "is_animation":
        cond = qm.FieldCondition(key="is_animation", match=qm.MatchValue(value=value == "true"))
        return [cond], []
    raise ValueError(f"unknown filter key: {key}")


def to_qdrant_filter(hard_filters: Mapping[str, str] | None) -> qm.Filter | None:
    """hard_filters를 Qdrant 필터로. 비어 있으면 None."""
    must: list[qm.Condition] = []
    must_not: list[qm.Condition] = []
    for key, value in (hard_filters or {}).items():
        m, n = _condition(key, value)
        must += m
        must_not += n
    if not must and not must_not:
        return None
    return qm.Filter(must=must or None, must_not=must_not or None)


def matches(attrs: MovieAttrs, key: str, value: str) -> bool:
    """영화가 조건 하나를 만족하는지. to_qdrant_filter와 같은 의미다."""
    if key == "decade":
        return attrs.decade == value
    if key == "country":
        if value == COUNTRY_OTHER:
            return attrs.country is not None and attrs.country != COUNTRY_KR
        return attrs.country == value
    if key == "genre":
        return value in attrs.genres
    if key == "is_animation":
        return attrs.is_animation == (value == "true")
    raise ValueError(f"unknown filter key: {key}")


def matches_any(attrs: MovieAttrs, soft_filters: Mapping[str, str] | None) -> bool:
    return any(matches(attrs, k, v) for k, v in (soft_filters or {}).items())
