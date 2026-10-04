"""검색 에이전트 그래프 (SPEC §8.2).

    START → analyze_input → rewrite_query → retrieve → aggregate → verify
    verify --(확신도 ≥ 임계값 / 재질문 횟수 소진 / 엔트로피 0)--> answer → END
    verify --(그 외)--> ask → clarify(interrupt) → retrieve

SPEC의 clarify를 ask(질문 생성)와 clarify(interrupt·답 반영)로 나눴다(nodes/clarify.py 참고).
재개: graph.invoke(Command(resume=<선택값>), config={"configurable": {"thread_id": session_id}})
"""

from typing import Any

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from app.agent.nodes.analyze import analyze_input
from app.agent.nodes.answer import answer
from app.agent.nodes.clarify import ask, clarify
from app.agent.nodes.retrieve import aggregate, retrieve
from app.agent.nodes.rewrite import rewrite_query
from app.agent.nodes.verify import route_after_verify, verify
from app.agent.state import SearchState


def build_graph(checkpointer: BaseCheckpointSaver[Any]) -> CompiledStateGraph[Any, Any, Any, Any]:
    g = StateGraph(SearchState)
    g.add_node("analyze_input", analyze_input)
    g.add_node("rewrite_query", rewrite_query)
    g.add_node("retrieve", retrieve)
    g.add_node("aggregate", aggregate)
    g.add_node("verify", verify)
    g.add_node("ask", ask)
    g.add_node("clarify", clarify)
    g.add_node("answer", answer)

    g.add_edge(START, "analyze_input")
    g.add_edge("analyze_input", "rewrite_query")
    g.add_edge("rewrite_query", "retrieve")
    g.add_edge("retrieve", "aggregate")
    g.add_edge("aggregate", "verify")
    g.add_conditional_edges("verify", route_after_verify, {"ask": "ask", "answer": "answer"})
    g.add_edge("ask", "clarify")
    g.add_edge("clarify", "retrieve")
    g.add_edge("answer", END)
    return g.compile(checkpointer=checkpointer)


def initial_state(session_id: str, query_text: str | None, image_key: str | None) -> SearchState:
    return {
        "session_id": session_id,
        "query_text": query_text,
        "image_key": image_key,
        "image_caption": None,
        "rewritten": None,
        "hard_filters": {},
        "asked_attrs": [],
        "scene_hits": [],
        "plot_hits": [],
        "movie_candidates": [],
        "verified": [],
        "confidence": 0.0,
        "clarify_choice": None,
        "clarify_turns": 0,
        "pending_question": None,
        "result": None,
        "cost_usd": 0.0,
        "timings_ms": {},
    }
