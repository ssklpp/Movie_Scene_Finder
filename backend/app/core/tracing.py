"""LangSmith 추적 설정.

`setup_tracing()`을 부른 프로세스(서버, 평가에서 켰을 때)만 추적한다. pydantic 설정은
환경 변수로 내보내지 않으므로 `.env`에 켜 두어도 파이프라인(캡셔닝 등)은 추적되지 않는다.

- LangGraph 노드는 LangSmith 전역 설정을 따라 자동으로 추적된다.
- OpenAI SDK 호출은 `core/llm.py`가 `wrap_openai`로 감싸야 프롬프트·응답·토큰이 보인다.
- 사용자가 올린 사진(base64 data URL)은 보내지 않고 자리 표시 문자열로 바꾼다.
"""

import logging
import uuid
import warnings
from typing import Any

import langsmith
from langsmith.wrappers import wrap_openai
from openai import OpenAI

from app.core.config import get_settings

logger = logging.getLogger(__name__)

IMAGE_PLACEHOLDER = "[image omitted]"

_enabled = False
_client: langsmith.Client | None = None
_project = ""
# 피드백에 붙일 프로젝트 UUID. 첫 피드백 때 이름으로 한 번 조회한다
_project_id: uuid.UUID | None = None


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
    global _enabled, _client, _project, _project_id
    s = get_settings()
    _project_id = None
    if not (s.langsmith_tracing and s.langsmith_api_key):
        langsmith.configure(enabled=False)
        _enabled, _client = False, None
        return False
    # wrap_openai가 구조화 출력을 직렬화할 때 호출마다 내는 pydantic 경고(기록에는 지장 없음)
    warnings.filterwarnings("ignore", message="Pydantic serializer warnings", category=UserWarning)
    client = langsmith.Client(api_key=s.langsmith_api_key, hide_inputs=redact_images)
    langsmith.configure(client=client, enabled=True, project_name=project or s.langsmith_project)
    _enabled, _client, _project = True, client, project or s.langsmith_project
    logger.info("LangSmith tracing on (project=%s)", _project)
    return True


def tracing_enabled() -> bool:
    return _enabled


def send_feedback(run_id: uuid.UUID, is_correct: bool, movie_id: int) -> None:
    """사용자 정답/오답을 그 검색의 트레이스에 `user_correct`(1/0)로 붙인다.

    `/feedback`의 백그라운드 작업으로 돈다. 실패해도 사용자 응답과 무관하므로 로그만 남긴다.
    """
    global _project_id
    if not _enabled or _client is None:
        return
    try:
        if _project_id is None:
            _project_id = _client.read_project(project_name=_project).id
        # 프로젝트(session_id) 없이 만드는 피드백은 SDK가 곧 막는다고 경고한다(langsmith 0.14)
        _client.create_feedback(
            run_id,
            key="user_correct",
            score=int(is_correct),
            comment=f"movie_id={movie_id}",
            trace_id=run_id,  # 루트 run이라 trace ID와 같다
            session_id=_project_id,
        )
    except Exception:
        logger.warning("LangSmith feedback failed for run %s", run_id, exc_info=True)


def traced_client(client: OpenAI) -> OpenAI:
    """추적이 켜져 있으면 OpenAI 클라이언트를 LangSmith 래퍼로 감싼다."""
    return wrap_openai(client) if _enabled else client
