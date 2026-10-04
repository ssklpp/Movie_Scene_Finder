"""LangSmith 추적 설정.

`setup_tracing()`을 부른 프로세스(서버, 평가에서 켰을 때)만 추적한다. pydantic 설정은
환경 변수로 내보내지 않으므로 `.env`에 켜 두어도 파이프라인(캡셔닝 등)은 추적되지 않는다.

- LangGraph 노드는 LangSmith 전역 설정을 따라 자동으로 추적된다.
- OpenAI SDK 호출은 `core/llm.py`가 `wrap_openai`로 감싸야 프롬프트·응답·토큰이 보인다.
- 사용자가 올린 사진(base64 data URL)은 보내지 않고 자리 표시 문자열로 바꾼다.
"""

import logging
import warnings
from typing import Any

import langsmith
from langsmith.wrappers import wrap_openai
from openai import OpenAI

from app.core.config import get_settings

logger = logging.getLogger(__name__)

IMAGE_PLACEHOLDER = "[image omitted]"

_enabled = False


def redact_images(data: Any) -> Any:
    """dict·list를 따라가며 `data:image/...` 문자열을 자리 표시 문자열로 바꾼다."""
    if isinstance(data, dict):
        return {k: redact_images(v) for k, v in data.items()}
    if isinstance(data, list):
        return [redact_images(v) for v in data]
    if isinstance(data, str) and data.startswith("data:image/"):
        return IMAGE_PLACEHOLDER
    return data


def setup_tracing(project: str | None = None) -> bool:
    """설정(LANGSMITH_TRACING, LANGSMITH_API_KEY)이 있으면 추적을 켠다. 켰으면 True."""
    global _enabled
    s = get_settings()
    if not (s.langsmith_tracing and s.langsmith_api_key):
        langsmith.configure(enabled=False)
        _enabled = False
        return False
    # wrap_openai가 구조화 출력을 직렬화할 때 호출마다 내는 pydantic 경고(기록에는 지장 없음)
    warnings.filterwarnings("ignore", message="Pydantic serializer warnings", category=UserWarning)
    client = langsmith.Client(api_key=s.langsmith_api_key, hide_inputs=redact_images)
    langsmith.configure(client=client, enabled=True, project_name=project or s.langsmith_project)
    _enabled = True
    logger.info("LangSmith tracing on (project=%s)", project or s.langsmith_project)
    return True


def tracing_enabled() -> bool:
    return _enabled


def traced_client(client: OpenAI) -> OpenAI:
    """추적이 켜져 있으면 OpenAI 클라이언트를 LangSmith 래퍼로 감싼다."""
    return wrap_openai(client) if _enabled else client
