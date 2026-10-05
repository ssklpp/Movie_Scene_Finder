"""에이전트 실행기: 그래프를 돌리며 SSE 이벤트(SPEC §9)를 만들고, 세션이 끝나면 sessions에 기록한다.

API와 분리해 두어 FastAPI 없이도 테스트할 수 있다. 그래프는 동기 실행이라 API는 이 제너레이터를
스레드에서 돌린다.
"""

import logging
import time
import uuid
from collections.abc import Iterator
from decimal import Decimal
from typing import Any, Protocol

from langchain_core.runnables import RunnableConfig
from langgraph.types import Command

from app.agent.graph import build_graph, has_query, initial_state
from app.agent.state import Question, ResultItem, SearchState
from app.db.models import Session as SessionRow
from app.db.session import SessionLocal

logger = logging.getLogger(__name__)

# 노드가 끝날 때 보낼 status 이벤트(SPEC: step = rewrite | retrieve | verify)
STATUS = {
    "analyze_input": ("analyze", "사진을 살펴봤어요"),
    "rewrite_query": ("rewrite", "기억을 검색어로 정리했어요"),
    "retrieve": ("retrieve", "비슷한 장면을 찾았어요"),
    "verify": ("verify", "후보 영화를 확인했어요"),
}
REQUEST_TIMEOUT_S = 30.0
TIMEOUT_MESSAGE = "처리 시간이 30초를 넘었어요."
IMAGE_UNREADABLE_MESSAGE = (
    "사진에서 장면을 읽지 못했어요. 다른 사진을 올리거나 기억나는 장면을 글로 적어 주세요."
)


# {"event": 이름, "data": JSON으로 보낼 dict}
Event = dict[str, Any]


def event(name: str, data: dict[str, Any]) -> Event:
    return {"event": name, "data": data}


class SessionStore(Protocol):
    def create(self, session_id: str, query_text: str | None, image_key: str | None) -> None: ...
    def finish(self, session_id: str, state: SearchState) -> None: ...
    def exists(self, session_id: str) -> bool: ...


class SqlSessionStore:
    """sessions 테이블(SPEC §5.1)."""

    def create(self, session_id: str, query_text: str | None, image_key: str | None) -> None:
        with SessionLocal.begin() as db:
            db.add(SessionRow(id=uuid.UUID(session_id), query_text=query_text, image_key=image_key))

    def finish(self, session_id: str, state: SearchState) -> None:
        rewritten = state.get("rewritten")
        with SessionLocal.begin() as db:
            row = db.get(SessionRow, uuid.UUID(session_id))
            if row is None:
                return
            row.rewritten = rewritten.model_dump() if rewritten else None
            row.hard_filters = dict(state.get("hard_filters", {}))
            row.clarify_turns = state.get("clarify_turns", 0)
            row.result_movie_ids = [r.movie_id for r in state.get("result") or []]
            row.confidence = state.get("confidence")
            # 사용자가 재질문에 답하느라 기다린 시간은 빼고 처리 시간만 센다
            row.latency_ms = sum(state.get("timings_ms", {}).values())
            row.cost_usd = Decimal(str(round(state.get("cost_usd", 0.0), 6)))

    def exists(self, session_id: str) -> bool:
        try:
            key = uuid.UUID(session_id)
        except ValueError:
            return False
        with SessionLocal() as db:
            return db.get(SessionRow, key) is not None


def question_event(q: Question) -> Event:
    return event(
        "question",
        {
            "text": q.text,
            "options": [o.value for o in q.options],
            "labels": [o.label for o in q.options],
            "attr": q.attr,
        },
    )


def result_event(items: list[ResultItem], confidence: float) -> Event:
    return event(
        "result",
        {"items": [i.model_dump() for i in items], "confidence": round(confidence, 4)},
    )


class AgentRuntime:
    def __init__(self, checkpointer: Any, store: SessionStore) -> None:
        self.graph = build_graph(checkpointer)
        self.store = store

    def _config(self, session_id: str) -> RunnableConfig:
        return {"configurable": {"thread_id": session_id}}

    def pending_question(self, session_id: str) -> Question | None:
        """재질문 답을 기다리는 세션이면 그 질문."""
        snapshot = self.graph.get_state(self._config(session_id))
        if "clarify" not in snapshot.next:
            return None
        q = snapshot.values.get("pending_question")
        return q if isinstance(q, Question) else None

    def start(
        self, query_text: str | None, image_key: str | None, session_id: str | None = None
    ) -> Iterator[Event]:
        session_id = session_id or str(uuid.uuid4())
        self.store.create(session_id, query_text, image_key)
        yield event("session", {"session_id": session_id})
        yield from self._run(session_id, initial_state(session_id, query_text, image_key), "search")

    def resume(self, session_id: str, value: str) -> Iterator[Event]:
        yield event("session", {"session_id": session_id})
        yield from self._run(session_id, Command(resume=value), "answer")

    def _run(self, session_id: str, graph_input: Any, request: str) -> Iterator[Event]:
        # LangSmith: 요청마다 trace 하나. session_id 메타데이터로 첫 검색과 재질문 답을 묶는다.
        config: RunnableConfig = {
            **self._config(session_id),
            "run_name": request,
            "metadata": {"session_id": session_id, "request": request},
        }
        started = time.perf_counter()
        try:
            for update in self.graph.stream(graph_input, config, stream_mode="updates"):
                for node, changes in update.items():
                    if node not in STATUS:
                        continue
                    if node == "analyze_input" and not (changes or {}).get("image_caption"):
                        continue  # 텍스트 질의는 사진 분석 단계가 없다
                    step, message = STATUS[node]
                    yield event("status", {"step": step, "message": message})
                if time.perf_counter() - started > REQUEST_TIMEOUT_S:
                    yield event("error", {"code": "timeout", "message": TIMEOUT_MESSAGE})
                    return
        except Exception:
            logger.exception("agent failed for session %s", session_id)
            yield event("error", {"code": "internal", "message": "검색 중 오류가 났어요."})
            return

        snapshot = self.graph.get_state(config)
        state: SearchState = snapshot.values  # type: ignore[assignment]
        if "clarify" in snapshot.next and state.get("pending_question") is not None:
            q = state["pending_question"]
            assert q is not None
            yield question_event(q)
            return
        self.store.finish(session_id, state)
        if not has_query(state):
            # 사진만 보냈는데 캡션을 못 만들었다. 같은 사진으로는 다시 해도 소용없어
            # 다른 방법을 안내한다.
            yield event("error", {"code": "image_unreadable", "message": IMAGE_UNREADABLE_MESSAGE})
            return
        yield result_event(state.get("result") or [], state.get("confidence", 0.0))
