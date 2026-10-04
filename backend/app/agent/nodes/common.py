import logging
import time
from collections.abc import Callable
from functools import wraps
from typing import Any, Protocol

from app.agent.state import SearchState

logger = logging.getLogger("app.agent")

# gpt-6-luna(추론 모델) 텍스트 호출 옵션. SPEC: reasoning effort low.
LLM_KWARGS: dict[str, Any] = {"reasoning_effort": "low", "max_completion_tokens": 2000}


class Node(Protocol):
    """LangGraph 노드 형태: state라는 이름의 인자를 받아 바뀐 필드만 돌려준다."""

    def __call__(self, state: SearchState) -> SearchState: ...


def timed(name: str) -> Callable[[Node], Node]:
    """노드 소요 시간을 timings_ms[name]에 더한다."""

    def decorator(fn: Node) -> Node:
        @wraps(fn)
        def wrapper(state: SearchState) -> SearchState:
            started = time.perf_counter()
            update = fn(state)
            update["timings_ms"] = {name: round((time.perf_counter() - started) * 1000)}
            return update

        return wrapper

    return decorator
