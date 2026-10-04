"""analyze_input: 이미지가 있으면 색인과 같은 프롬프트로 SceneCaption을 만든다."""

from app.agent.nodes.common import logger, timed
from app.agent.state import SearchState
from app.core import llm
from app.core.config import get_settings
from app.core.uploads import load_upload
from app.search.caption import OPENAI_CAPTION_KWARGS, SceneCaption, build_messages


@timed("analyze_input")
def analyze_input(state: SearchState) -> SearchState:
    key = state.get("image_key")
    if not key:
        return {"image_caption": None, "cost_usd": 0.0}
    data, mime = load_upload(key)
    try:
        caption, stats = llm.parse(
            build_messages(data, mime),
            SceneCaption,
            model=get_settings().llm_model_default,
            **OPENAI_CAPTION_KWARGS,
        )
    except Exception as e:
        logger.warning("image caption failed for %s: %s", key, e)
        return {"image_caption": None, "cost_usd": 0.0}
    return {"image_caption": caption, "cost_usd": stats.cost_usd}
