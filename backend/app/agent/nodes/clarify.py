"""재질문 (§7.6). LangGraph는 interrupt() 뒤 재개할 때 노드를 처음부터 다시 실행하므로,
질문 문장을 만드는 LLM 호출(ask)과 답을 기다리는 interrupt(clarify)를 다른 노드로 나눈다.
"""

from typing import Any

from langgraph.types import interrupt

from app.agent.nodes.common import LLM_KWARGS, logger, timed
from app.agent.prompts import question_messages
from app.agent.state import Question, SearchState
from app.core import llm
from app.core.config import get_settings
from app.search.clarify import ATTR_NAMES, FALLBACK_QUESTIONS, UNKNOWN, apply_answer


@timed("ask")
def ask(state: SearchState) -> SearchState:
    choice = state["clarify_choice"]
    assert choice is not None  # route_after_verify가 보장한다
    text = FALLBACK_QUESTIONS[choice.attr]
    cost = 0.0
    try:
        resp, stats = llm.chat(
            question_messages(
                ATTR_NAMES[choice.attr], [o.label for o in choice.options], state.get("query_text")
            ),
            model=get_settings().llm_model_default,
            **LLM_KWARGS,
        )
        cost = stats.cost_usd
        generated = (resp.choices[0].message.content or "").strip() if resp.choices else ""
        if generated:
            text = generated.splitlines()[0]
    except Exception as e:
        logger.warning("question generation failed, using fallback: %s", e)
    return {
        "pending_question": Question(attr=choice.attr, text=text, options=choice.options),
        "cost_usd": cost,
    }


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
