"""API(SPEC §9) 테스트. 에이전트는 가짜 LLM·검색과 메모리 체크포인터로 돌린다.

DB가 필요한 테스트(피드백, 영화 조회, sessions 기록)는 Postgres에 연결되지 않으면 건너뛴다.
"""

import json
import uuid
from collections.abc import Callable, Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy import delete, text

from app.agent.checkpoint import make_serde
from app.agent.runtime import AgentRuntime, SqlSessionStore
from app.agent.state import SearchState
from app.api.routes_search import limiter
from app.core.config import get_settings
from app.db.models import Feedback, Movie
from app.db.models import Session as SessionRow
from app.db.session import SessionLocal
from app.main import app
from tests.test_agent import ATTRS, MOVIES, Fakes


class MemoryStore:
    def __init__(self) -> None:
        self.created: list[str] = []
        self.finished: dict[str, SearchState] = {}

    def create(self, session_id: str, query_text: str | None, image_key: str | None) -> None:
        self.created.append(session_id)

    def finish(self, session_id: str, state: SearchState) -> None:
        self.finished[session_id] = state

    def exists(self, session_id: str) -> bool:
        return session_id in self.created


def parse_sse(body: str) -> list[tuple[str, dict[str, Any]]]:
    events = []
    for block in body.replace("\r\n", "\n").split("\n\n"):
        name, data = None, None
        for line in block.splitlines():
            if line.startswith("event:"):
                name = line.split(":", 1)[1].strip()
            elif line.startswith("data:"):
                data = json.loads(line.split(":", 1)[1].strip())
        if name and data is not None:
            events.append((name, data))
    return events


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> Callable[..., tuple[TestClient, Fakes, Any]]:
    def _make(
        verify_scores: Callable[[int], dict[int, float]], store: Any = None
    ) -> tuple[TestClient, Fakes, Any]:
        fakes = Fakes(verify_scores)
        monkeypatch.setattr("app.core.llm.parse", fakes.parse)
        monkeypatch.setattr("app.core.llm.chat", fakes.chat)
        monkeypatch.setattr("app.search.hybrid.retrieve", fakes.retrieve)
        monkeypatch.setattr("app.agent.movies.all_movies", lambda: MOVIES)
        store = store or MemoryStore()
        app.state.runtime = AgentRuntime(InMemorySaver(serde=make_serde()), store)
        limiter.reset()
        return TestClient(app), fakes, store

    return _make


def test_search_text_streams_session_status_result(client: Callable[..., Any]) -> None:
    tc, _, store = client(lambda n: {1: 0.95, 2: 0.2})
    resp = tc.post("/search", data={"text": "반지하에 물이 차는 장면"})
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")
    events = parse_sse(resp.text)
    names = [n for n, _ in events]
    assert names[0] == "session" and names[-1] == "result"
    assert [d["step"] for n, d in events if n == "status"] == ["rewrite", "retrieve", "verify"]
    session_id = events[0][1]["session_id"]
    result = events[-1][1]
    assert result["items"][0]["movie_id"] == 1 and result["items"][0]["title_ko"] == "기생충"
    assert result["items"][0]["evidence"][0]["scene_id"] == "1_backdrop_0"
    assert result["confidence"] >= 0.7
    assert session_id in store.finished  # 결과가 나오면 세션 기록


def test_question_then_answer_resumes(client: Callable[..., Any]) -> None:
    tc, fakes, store = client(lambda n: {1: 0.6, 2: 0.55} if n == 1 else {1: 0.9})
    events = parse_sse(tc.post("/search", data={"text": "물 차는 집"}).text)
    assert events[-1][0] == "question"
    q = events[-1][1]
    assert q["attr"] == "decade" and q["options"] == ["2010s", "2000s", "unknown"]
    assert q["labels"][-1] == "모르겠어요"
    session_id = events[0][1]["session_id"]
    assert session_id not in store.finished  # 아직 끝나지 않았다

    resp = tc.post(f"/search/{session_id}/answer", json={"value": "2010s"})
    events = parse_sse(resp.text)
    assert events[0] == ("session", {"session_id": session_id})
    assert events[-1][0] == "result"
    assert [i["movie_id"] for i in events[-1][1]["items"]] == [1]
    assert fakes.retrieve_calls[-1][1] == {"decade": "2010s"}
    assert store.finished[session_id]["clarify_turns"] == 1


def test_answer_errors(client: Callable[..., Any]) -> None:
    tc, _, _ = client(lambda n: {1: 0.6, 2: 0.55})
    events = parse_sse(tc.post("/search", data={"text": "q"}).text)
    sid = events[0][1]["session_id"]
    assert tc.post(f"/search/{sid}/answer", json={"value": "1990s"}).status_code == 400
    assert tc.post(f"/search/{uuid.uuid4()}/answer", json={"value": "2010s"}).status_code == 409


def test_search_validation(client: Callable[..., Any]) -> None:
    tc, _, _ = client(lambda n: {1: 0.95})
    assert tc.post("/search", data={"text": "  "}).status_code == 400
    gif = {"image": ("a.gif", b"GIF89a", "image/gif")}
    assert tc.post("/search", files=gif).status_code == 400
    big = {"image": ("a.jpg", b"\xff" * (5 * 1024 * 1024 + 1), "image/jpeg")}
    assert tc.post("/search", files=big).status_code == 413


def test_search_with_image(
    client: Callable[..., Any], monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    from app.core import uploads

    monkeypatch.setattr(uploads, "UPLOAD_DIR", tmp_path)
    monkeypatch.setattr(
        "app.api.routes_search.save_upload", lambda d, s: uploads.save_upload(d, s, tmp_path)
    )
    monkeypatch.setattr(
        "app.agent.nodes.analyze.load_upload", lambda k: uploads.load_upload(k, tmp_path)
    )
    tc, _, _ = client(lambda n: {1: 0.95})
    files = {"image": ("still.png", b"\x89PNG....", "image/png")}
    events = parse_sse(tc.post("/search", files=files).text)
    assert next(d["step"] for n, d in events if n == "status") == "analyze"
    assert events[-1][0] == "result"


def test_unreadable_image_becomes_guidance_error(
    client: Callable[..., Any], monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    from app.core import uploads

    monkeypatch.setattr(
        "app.api.routes_search.save_upload", lambda d, s: uploads.save_upload(d, s, tmp_path)
    )
    monkeypatch.setattr(
        "app.agent.nodes.analyze.load_upload", lambda k: uploads.load_upload(k, tmp_path)
    )
    tc, fakes, store = client(lambda n: {1: 0.95})
    fakes.caption_fails = True
    files = {"image": ("still.png", b"\x89PNG....", "image/png")}
    events = parse_sse(tc.post("/search", files=files).text)
    assert [n for n, _ in events] == ["session", "error"]
    assert events[-1][1]["code"] == "image_unreadable"
    assert len(store.finished) == 1  # 세션 비용·지연 기록은 남긴다


def test_rate_limit_per_ip(client: Callable[..., Any], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "rate_limit_per_day", 2)
    tc, _, _ = client(lambda n: {1: 0.95})
    assert tc.post("/search", data={"text": "a"}).status_code == 200
    assert tc.post("/search", data={"text": "b"}).status_code == 200
    assert tc.post("/search", data={"text": "c"}).status_code == 429


def test_agent_error_becomes_error_event(
    client: Callable[..., Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    tc, _, _ = client(lambda n: {1: 0.95})

    def boom(*a: Any, **k: Any) -> Any:
        raise RuntimeError("qdrant down")

    monkeypatch.setattr("app.search.hybrid.retrieve", boom)
    events = parse_sse(tc.post("/search", data={"text": "q"}).text)
    assert events[-1] == ("error", {"code": "internal", "message": "검색 중 오류가 났어요."})


# --- DB가 필요한 테스트 -------------------------------------------------------


@pytest.fixture
def db_movie() -> Iterator[int]:
    """임시 영화 1편. Postgres에 연결되지 않으면 건너뛴다."""
    try:
        with SessionLocal() as db:
            db.execute(text("SELECT 1"))
    except Exception:
        pytest.skip("Postgres not available")
    with SessionLocal.begin() as db:
        movie = Movie(tmdb_id=990_001, title_ko="테스트 영화", year=2001, genres=["드라마"])
        db.add(movie)
        db.flush()
        movie_id = movie.id
    yield movie_id
    with SessionLocal.begin() as db:
        db.execute(delete(Feedback).where(Feedback.movie_id == movie_id))
        db.execute(delete(Movie).where(Movie.id == movie_id))


def test_session_recorded_and_feedback(client: Callable[..., Any], db_movie: int) -> None:
    tc, _, _ = client(lambda n: {1: 0.95, 2: 0.2}, store=SqlSessionStore())
    events = parse_sse(tc.post("/search", data={"text": "반지하"}).text)
    sid = events[0][1]["session_id"]
    with SessionLocal() as db:
        row = db.get(SessionRow, uuid.UUID(sid))
        assert row is not None and row.query_text == "반지하"
        assert row.result_movie_ids == [1, 2] and row.cost_usd is not None and row.cost_usd > 0
        assert row.latency_ms is not None and row.confidence is not None

    ok = tc.post("/feedback", json={"session_id": sid, "movie_id": db_movie, "is_correct": True})
    assert ok.status_code == 204
    missing = {"session_id": str(uuid.uuid4()), "movie_id": db_movie, "is_correct": False}
    assert tc.post("/feedback", json=missing).status_code == 404
    bad_movie = {"session_id": sid, "movie_id": -1, "is_correct": False}
    assert tc.post("/feedback", json=bad_movie).status_code == 404
    with SessionLocal.begin() as db:
        db.execute(delete(Feedback).where(Feedback.session_id == uuid.UUID(sid)))
        db.execute(delete(SessionRow).where(SessionRow.id == uuid.UUID(sid)))


def test_get_movie(db_movie: int) -> None:
    tc = TestClient(app)
    body = tc.get(f"/movies/{db_movie}").json()
    assert body["title_ko"] == "테스트 영화" and body["genres"] == ["드라마"]
    assert body["scenes"] == [] and body["is_animation"] is False
    assert tc.get("/movies/-1").status_code == 404


def test_health() -> None:
    assert TestClient(app).get("/health").json() == {"status": "ok"}


def test_cors_allows_frontend_origin_only() -> None:
    tc = TestClient(app)
    preflight = {"Access-Control-Request-Method": "POST"}
    ok = tc.options("/search", headers={"Origin": "http://localhost:3000", **preflight})
    assert ok.headers.get("access-control-allow-origin") == "http://localhost:3000"
    other = tc.options("/search", headers={"Origin": "https://evil.example", **preflight})
    assert "access-control-allow-origin" not in other.headers


def test_unused_fixture_data_is_consistent() -> None:
    assert set(ATTRS) == set(MOVIES)
