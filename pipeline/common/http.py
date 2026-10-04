"""외부 API 호출 공용: 타임아웃 + 지수 백오프 재시도(최대 3회) (SPEC §0.4)."""

import logging
import time
from typing import Any

import httpx

logger = logging.getLogger(__name__)

RETRY_STATUS = {429, 500, 502, 503, 504}


def get_json(
    client: httpx.Client,
    url: str,
    params: dict[str, Any] | None = None,
    max_retries: int = 3,
    backoff_s: float = 1.0,
) -> Any:
    """GET 요청 후 JSON을 돌려준다. 429·5xx·네트워크 오류는 1s, 2s, 4s 간격으로 재시도한다."""
    for attempt in range(max_retries + 1):
        try:
            resp = client.get(url, params=params)
            if resp.status_code not in RETRY_STATUS:
                resp.raise_for_status()
                return resp.json()
            error: Exception = httpx.HTTPStatusError(
                f"retryable status {resp.status_code}", request=resp.request, response=resp
            )
        except httpx.TransportError as e:
            error = e
        if attempt == max_retries:
            raise error
        delay = backoff_s * 2**attempt
        logger.warning("GET %s failed (%s); retry %d in %.1fs", url, error, attempt + 1, delay)
        time.sleep(delay)
    raise AssertionError("unreachable")
