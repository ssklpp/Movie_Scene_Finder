"""POST /search, POST /search/{session_id}/answer (SPEC §9). 응답은 SSE 스트림이다."""

import json
from collections.abc import AsyncIterator, Iterator
from typing import Annotated

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from slowapi import Limiter
from slowapi.util import get_remote_address
from sse_starlette import EventSourceResponse, ServerSentEvent
from starlette.concurrency import iterate_in_threadpool

from app.agent.runtime import AgentRuntime, Event
from app.api.schemas import AnswerRequest
from app.core.config import get_settings
from app.core.uploads import save_upload

router = APIRouter()
limiter = Limiter(key_func=get_remote_address)

MAX_IMAGE_BYTES = 5 * 1024 * 1024
SUFFIX_BY_TYPE = {"image/jpeg": ".jpg", "image/png": ".png"}


def get_runtime(request: Request) -> AgentRuntime:
    runtime: AgentRuntime = request.app.state.runtime
    return runtime


def daily_limit() -> str:
    return f"{get_settings().rate_limit_per_day}/day"


def sse(events: Iterator[Event]) -> EventSourceResponse:
    """그래프는 동기 실행이라 스레드에서 돌리며 이벤트를 흘려보낸다."""

    async def stream() -> AsyncIterator[ServerSentEvent]:
        async for e in iterate_in_threadpool(events):
            yield ServerSentEvent(event=e["event"], data=json.dumps(e["data"], ensure_ascii=False))

    return EventSourceResponse(stream())


@router.post("/search")
@limiter.limit(daily_limit)
async def search(
    request: Request,
    text: Annotated[str | None, Form()] = None,
    image: Annotated[UploadFile | None, File()] = None,
) -> EventSourceResponse:
    text = (text or "").strip() or None
    image_key = None
    if image is not None and image.filename:
        suffix = SUFFIX_BY_TYPE.get(image.content_type or "")
        if suffix is None:
            raise HTTPException(400, "image must be JPEG or PNG")
        data = await image.read(MAX_IMAGE_BYTES + 1)
        if len(data) > MAX_IMAGE_BYTES:
            raise HTTPException(413, "image must be 5MB or smaller")
        image_key = save_upload(data, suffix)
    if text is None and image_key is None:
        raise HTTPException(400, "text or image is required")
    return sse(get_runtime(request).start(text, image_key))


@router.post("/search/{session_id}/answer")
async def answer(request: Request, session_id: str, body: AnswerRequest) -> EventSourceResponse:
    runtime = get_runtime(request)
    question = runtime.pending_question(session_id)
    if question is None:
        raise HTTPException(409, "session is not waiting for an answer")
    if body.value not in {o.value for o in question.options}:
        raise HTTPException(400, f"value must be one of the options for {question.attr}")
    return sse(runtime.resume(session_id, body.value))
