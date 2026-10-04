"""verify: LLM 검증 → 재정렬 → 확신도(§7.5), 재질문이 필요하면 속성을 고른다(§7.6)."""

from app.agent.movies import movie_info
from app.agent.nodes.common import llm_kwargs, logger, timed
from app.agent.prompts import verify_messages
from app.agent.state import SearchState
from app.core import llm
from app.core.config import get_settings
from app.search.clarify import choose_attribute
from app.search.confidence import Verified, VerifyOutput, confidence, rerank


@timed("verify")
def verify(state: SearchState) -> SearchState:
    s = get_settings()
    candidates = state.get("movie_candidates", [])
    if not candidates:
        return {"verified": [], "confidence": 0.0, "clarify_choice": None, "cost_usd": 0.0}

    infos = {c.movie_id: info for c in candidates if (info := movie_info(c.movie_id))}
    verified: list[Verified] = []
    cost = 0.0
    try:
        out, stats = llm.parse(
            verify_messages(state.get("query_text"), state.get("image_caption"), candidates, infos),
            VerifyOutput,
            model=s.llm_model_default,
            **llm_kwargs(s.verify_reasoning_effort),
        )
        cost = stats.cost_usd
        verified = out.items if out else []
    except Exception as e:  # 검증 실패 시 모두 0점 → 확신도 0 → 재질문(또는 집계 순서로 답)
        logger.warning("verify failed: %s", e)

    ranked = rerank(candidates, verified)
    conf = confidence([r.verified.score for r in ranked])
    turns = state.get("clarify_turns", 0)
    choice = None
    if conf < s.confidence_threshold and turns < s.max_clarify_turns:
        items = [(r.candidate.attrs, r.verified.score) for r in ranked]
        choice = choose_attribute(items, asked=state.get("asked_attrs", []))
    return {
        "movie_candidates": [r.candidate for r in ranked],
        "verified": [r.verified for r in ranked],
        "confidence": conf,
        "clarify_choice": choice,
        "cost_usd": cost,
    }


def route_after_verify(state: SearchState) -> str:
    """확신도가 충분하거나, 재질문을 다 썼거나, 물을 속성이 없으면(엔트로피 0) 답한다."""
    return "ask" if state.get("clarify_choice") is not None else "answer"
