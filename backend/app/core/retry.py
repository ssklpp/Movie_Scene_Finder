"""외부 호출(Qdrant 등) 재시도: 지수 백오프, 최대 3회 (SPEC §0.4).

파이프라인의 HTTP(httpx) 호출은 `pipeline.common.http.get`을 쓴다.
"""

import logging
import time
from collections.abc import Callable

logger = logging.getLogger(__name__)


def retry[T](fn: Callable[[], T], what: str, max_retries: int = 3, backoff_s: float = 1.0) -> T:
    """fn을 호출하고, 예외가 나면 1s, 2s, 4s 간격으로 최대 max_retries번 다시 시도한다."""
    for attempt in range(max_retries + 1):
        try:
            return fn()
        except Exception as e:
            if attempt == max_retries:
                raise
            delay = backoff_s * 2**attempt
            logger.warning("%s failed (%s); retry %d in %.1fs", what, e, attempt + 1, delay)
            time.sleep(delay)
    raise AssertionError("unreachable")
