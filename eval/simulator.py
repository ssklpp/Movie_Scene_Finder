"""재질문 시뮬레이터 (SPEC §11): 정답 영화의 속성으로 재질문에 자동으로 답한다.

정답 값이 선택지에 있으면 고르고, 없으면 "모르겠어요"를 고른다. 사람이 속성을 정확히 기억한다고
가정한 상한선이므로 실제 사용자보다 유리하다.
"""

from collections.abc import Mapping
from typing import Any

from app.search.clarify import UNKNOWN, attr_value
from app.search.filters import MovieAttrs


def simulated_answer(question: Mapping[str, Any], answer_attrs: MovieAttrs) -> str:
    """question은 interrupt 값({"attr", "options": [{"value", "label"}, ...], ...})이다."""
    truth = attr_value(answer_attrs, str(question["attr"]))
    options = {str(o["value"]) for o in question["options"]}
    return truth if truth is not None and truth in options else UNKNOWN
