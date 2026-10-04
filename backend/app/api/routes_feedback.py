"""POST /feedback (SPEC §9). 정답 여부는 regression 데이터셋(§11)의 재료가 된다."""

import uuid

from fastapi import APIRouter, HTTPException, Response

from app.api.schemas import FeedbackRequest
from app.db.models import Feedback, Movie
from app.db.models import Session as SessionRow
from app.db.session import SessionLocal

router = APIRouter()


@router.post("/feedback", status_code=204)
def feedback(body: FeedbackRequest) -> Response:
    try:
        session_id = uuid.UUID(body.session_id)
    except ValueError as e:
        raise HTTPException(404, "session not found") from e
    with SessionLocal.begin() as db:
        if db.get(SessionRow, session_id) is None:
            raise HTTPException(404, "session not found")
        if db.get(Movie, body.movie_id) is None:
            raise HTTPException(404, "movie not found")
        db.add(Feedback(session_id=session_id, movie_id=body.movie_id, is_correct=body.is_correct))
    return Response(status_code=204)
