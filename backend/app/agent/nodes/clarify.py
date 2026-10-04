"""재질문 (§7.6).

ask는 질문(속성별 고정 문장과 선택지)을 만들고, clarify는 interrupt()로 답을 기다려 반영한다.
LangGraph는 재개할 때 interrupt가 있는 노드를 처음부터 다시 실행하므로, 질문을 만드는 일과
기다리는 일을 다른 노드에 둔다(질문 문장을 LLM으로 만들던 때의 구조이며, 지금도 재개 시 같은
질문이 유지되도록 그대로 둔다).
"""

from typing import Any

from langgraph.types import interrupt

from app.agent.nodes.common import timed
from app.agent.state import Question, SearchState
from app.search.clarify import QUESTIONS, UNKNOWN, apply_answer


@timed("ask")
def ask(state: SearchState) -> SearchState:
    choice = state["clarify_choice"]
    assert choice is not None  # route_after_verify가 보장한다
    question = Question(attr=choice.attr, text=QUESTIONS[choice.attr], options=choice.options)
    return {"pending_question": question}


def answer_value(question: Question, resume: Any) -> str:
    """재개 값을 선택지 값으로. 선택지에 없으면 "모르겠어요"로 본다."""
    value = str(resume)
    return value if value in {o.value for o in question.options} else UNKNOWN


def clarify(state: SearchState) -> SearchState:
    question = state["pending_question"]
    assert question is not None
    value = answer_value(question, interrupt(question.model_dump()))
    return {
        "hard_filters": apply_answer(state.get("hard_filters", {}), question.attr, value),
        "asked_attrs": [*state.get("asked_attrs", []), question.attr],
        "clarify_turns": state.get("clarify_turns", 0) + 1,
        "pending_question": None,
        "clarify_choice": None,
    }
