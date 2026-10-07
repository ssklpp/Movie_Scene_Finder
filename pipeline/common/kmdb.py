"""KMDb(한국영화데이터베이스) 검색 API: 한국어 줄거리와 키워드.

외국 영화도 국내 개봉작이면 대부분 있다. 제목 검색 결과의 제목에는 `!HS … !HE` 강조 표시가 붙는다.
"""

import logging
import re
from typing import Any

import httpx

from pipeline.common.http import get_json

SEARCH_URL = "https://api.koreafilm.or.kr/openapi-data2/wisenut/search_api/search_json2.jsp"

MIN_RUNTIME_MIN = 40

_HIGHLIGHT = re.compile(r"!H[SE]")
_NON_WORD = re.compile(r"[\W_]+")


class KmdbClient:
    def __init__(self, api_key: str, timeout_s: float = 30.0) -> None:
        if not api_key:
            raise ValueError("KMDB_API_KEY is empty; set it in .env")
        self._key = api_key
        self._client = httpx.Client(timeout=timeout_s)
        # KMDb는 키를 쿼리 문자열로 받으므로 httpx의 요청 로그(INFO)에 키가 찍힌다.
        logging.getLogger("httpx").setLevel(logging.WARNING)

    def search(self, **params: Any) -> list[dict[str, Any]]:
        """`title=`, `titleEng=` 등으로 검색해 결과 목록을 돌려준다(최대 20건)."""
        query = {
            "collection": "kmdb_new2",
            "ServiceKey": self._key,
            "detail": "Y",
            "listCount": 20,
            **params,
        }
        data = get_json(self._client, SEARCH_URL, query)
        blocks = data.get("Data") or [{}]
        results: list[dict[str, Any]] = blocks[0].get("Result") or []
        return results

    def close(self) -> None:
        self._client.close()


def clean_title(title: str) -> str:
    """강조 표시를 지우고 공백을 하나로 줄인다."""
    return " ".join(_HIGHLIGHT.sub("", title).split())


def norm_title(title: str) -> str:
    """비교용: 강조 표시·공백·문장부호를 지우고 소문자로. "Volume 3"과 "Vol. 3"은 같게 본다."""
    return _NON_WORD.sub("", _HIGHLIGHT.sub("", title)).lower().replace("volume", "vol")


def title_variants(result: dict[str, Any]) -> set[str]:
    """제목, 영어 제목, 원제, 다른 제목들(`titleEtc`, `^`로 구분)의 비교용 형태."""
    names = [result.get("title", ""), result.get("titleEng", ""), result.get("titleOrg", "")]
    names += result.get("titleEtc", "").split("^")
    # 영어 제목 뒤에 붙는 로마자 표기 "(Gongdonggyeongbiguyeok)"는 떼어 낸 형태도 넣는다.
    names += [re.sub(r"\s*\([^)]*\)\s*$", "", n) for n in names]
    return {v for n in names if (v := norm_title(n))}


def years(result: dict[str, Any]) -> set[int]:
    """제작연도와 대표 개봉일 연도. TMDB 개봉연도와 1년쯤 다른 경우가 있다(곡성 2015 / 2016)."""
    found = set()
    for raw in (result.get("prodYear", ""), result.get("repRlsDate", "")[:4]):
        if raw.isdigit():
            found.add(int(raw))
    return found


def korean_plot(result: dict[str, Any]) -> str | None:
    for plot in result.get("plots", {}).get("plot", []):
        if plot.get("plotLang") == "한국어" and plot.get("plotText", "").strip():
            text: str = plot["plotText"].strip()
            return text
    return None


def keywords(result: dict[str, Any]) -> list[str]:
    """쉼표로 구분된 키워드를 순서를 지켜 중복 없이."""
    words = (w.strip() for w in result.get("keywords", "").split(","))
    return list(dict.fromkeys(w for w in words if w))


def pick_match(
    results: list[dict[str, Any]],
    title_ko: str | None,
    title_en: str | None,
    year: int | None,
    country: str | None,
) -> dict[str, Any] | None:
    """TMDB 영화와 같은 KMDb 항목을 고른다. 없으면 None.

    조건: 제목(한·영 중 하나)이 KMDb 제목 형태 중 하나와 같고, 연도 차이 1년 이내.
    TMDB 국가가 KR이면 KMDb 국가에 대한민국이 있어야 하고, KR이 아니면 대한민국 단독 제작은
    뺀다("X" 2022 미국 ↔ 같은 제목 한국 영화). 상영시간 40분 미만(단편, "풋티지" 홍보 상영본)도
    뺀다. 여럿이면 연도 차이가 작은 것.
    """
    wanted = {v for t in (title_ko, title_en) if t and (v := norm_title(t))}
    if not wanted or year is None:
        return None
    best: tuple[int, dict[str, Any]] | None = None
    for r in results:
        if not wanted & title_variants(r):
            continue
        diffs = [abs(y - year) for y in years(r)]
        if not diffs or min(diffs) > 1:
            continue
        nation = r.get("nation", "")
        if country == "KR" and "대한민국" not in nation:
            continue
        if country != "KR" and nation == "대한민국":
            continue
        runtime = r.get("runtime", "")
        if runtime.isdigit() and int(runtime) < MIN_RUNTIME_MIN:
            continue
        if best is None or min(diffs) < best[0]:
            best = (min(diffs), r)
    return best[1] if best else None
