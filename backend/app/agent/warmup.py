"""서버 시작 때 첫 요청이 느려지지 않도록 미리 준비한다.

측정상 첫 요청이 약 3초 더 걸렸다(Kiwi 사전 로딩, 영화 목록 조회, Qdrant·OpenAI 첫 연결).
준비가 실패해도 서버는 뜨고, 그 비용은 첫 요청이 치른다.
"""

import logging
import time
from collections.abc import Callable

from app.agent.movies import all_movies
from app.core import llm
from app.core.config import get_settings
from app.search import sparse
from app.search.qdrant import get_qdrant

logger = logging.getLogger(__name__)


def warm_up() -> None:
    started = time.perf_counter()
    steps: dict[str, Callable[[], object]] = {
        "kiwi": lambda: sparse.tokenize("기차 안의 좀비"),
        "movies": all_movies,
        "qdrant": lambda: get_qdrant().get_collection(get_settings().qdrant_scenes_alias),
        "openai": lambda: llm.embed(["warm up"]),  # 연결만 맺는다(비용 거의 0)
    }
    for name, step in steps.items():
        try:
            step()
        except Exception as e:
            logger.warning("warm-up %s failed: %s", name, e)
    logger.info("warm-up done in %dms", (time.perf_counter() - started) * 1000)
