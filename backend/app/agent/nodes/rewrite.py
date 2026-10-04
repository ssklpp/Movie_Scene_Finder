"""rewrite_query: 사용자 묘사(와 사진 묘사)를 Rewritten(SPEC §7.1)으로 정리한다."""

import re
from collections.abc import Collection

from app.agent.movies import known_genres
from app.agent.nodes.common import LLM_KWARGS, logger, timed
from app.agent.prompts import RewriteOutput, SoftFilterFields, rewrite_messages
from app.agent.state import Rewritten, SearchState
from app.core import llm
from app.core.config import get_settings

DECADE = re.compile(r"^\d{3}0s$")


def valid_soft_filters(fields: SoftFilterFields, genres: Collection[str]) -> dict[str, str]:
    """LLM 출력에서 형식이 맞는 조건만 남긴다(값의 의미는 search/filters.py)."""
    out: dict[str, str] = {}
    if fields.decade and DECADE.match(fields.decade):
        out["decade"] = fields.decade
    if fields.country in ("KR", "other"):
        out["country"] = fields.country
    if fields.genre and fields.genre in genres:
        out["genre"] = fields.genre
    if fields.is_animation in ("true", "false"):
        out["is_animation"] = fields.is_animation
    return out


def fallback(state: SearchState) -> Rewritten:
    caption = state.get("image_caption")
    text = state.get("query_text") or (caption.caption_ko if caption else "")
    return Rewritten(scene_ko=text, keywords_ko=[], soft_filters={})


@timed("rewrite_query")
def rewrite_query(state: SearchState) -> SearchState:
    genres = known_genres()
    try:
        out, stats = llm.parse(
            rewrite_messages(state.get("query_text"), state.get("image_caption"), genres),
            RewriteOutput,
            model=get_settings().llm_model_default,
            **LLM_KWARGS,
        )
    except Exception as e:
        logger.warning("rewrite failed, using raw query: %s", e)
        return {"rewritten": fallback(state), "cost_usd": 0.0}
    if out is None:
        return {"rewritten": fallback(state), "cost_usd": stats.cost_usd}
    rewritten = Rewritten(
        scene_ko=out.scene_ko or fallback(state).scene_ko,
        keywords_ko=out.keywords_ko,
        soft_filters=valid_soft_filters(out.soft_filters, genres),
    )
    return {"rewritten": rewritten, "cost_usd": stats.cost_usd}
