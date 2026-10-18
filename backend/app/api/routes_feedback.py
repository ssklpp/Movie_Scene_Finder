"""POST /feedback (SPEC §9). 정답 여부는 regression 데이터셋(§11)의 재료가 된다.

추적이 켜져 있으면 결과를 낸 요청의 LangSmith 트레이스에도 `user_correct`로 붙인다. 응답이
LangSmith를 기다리지 않도록 응답을 보낸 뒤 백그라운드 작업으로 보낸다.
"""

import uuid

from fastapi import APIRouter, BackgroundTasks, HTTPException, Response

from app.api.schemas import FeedbackRequest
from app.core.tracing import send_feedback
from app.db.models import Feedback, Movie
from app.db.models import Session as SessionRow
from app.db.session import SessionLocal

router = APIRouter()


@router.post("/feedback", status_code=204)
def feedback(body: FeedbackRequest, background: BackgroundTasks) -> Response:
    try:
        session_id = uuid.UUID(body.session_id)
    except ValueError as e:
        raise HTTPException(404, "session not found") from e
    with SessionLocal.begin() as db:
        session = db.get(SessionRow, session_id)
        if session is None:
            raise HTTPException(404, "session not found")
        if db.get(Movie, body.movie_id) is None:
            raise HTTPException(404, "movie not found")
        db.add(Feedback(session_id=session_id, movie_id=body.movie_id, is_correct=body.is_correct))
        run_id = session.trace_run_id
    if run_id is not None:
        background.add_task(send_feedback, run_id, body.is_correct, body.movie_id)
    return Response(status_code=204)
