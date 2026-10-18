import uuid
from collections.abc import Iterator
from typing import Any

import langsmith
import pytest
from openai import OpenAI

from app.core import tracing
from app.core.config import Settings


@pytest.fixture(autouse=True)
def tracing_off() -> Iterator[None]:
    yield
    langsmith.configure(client=None, enabled=False)
    tracing._enabled = False
    tracing._client = None
    tracing._project_id = None


class FakeLangSmith:
    PROJECT_ID = uuid.UUID(int=1)

    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.calls: list[tuple[Any, dict[str, Any]]] = []
        self.project_lookups = 0

    def read_project(self, *, project_name: str) -> Any:
        self.project_lookups += 1
        return type("Project", (), {"id": self.PROJECT_ID})()

    def create_feedback(self, run_id: Any, **kwargs: Any) -> None:
        if self.fail:
            raise ConnectionError("langsmith down")
        self.calls.append((run_id, kwargs))


def test_redact_images_replaces_data_urls_only() -> None:
    messages = [
        {"role": "system", "content": "사진 묘사: data:image/ 로 시작하지 않는 글은 그대로"},
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "장면 설명"},
                {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}},
            ],
        },
    ]
    out = tracing.redact_images({"messages": messages, "n": 1})
    assert out["n"] == 1
    assert out["messages"][0] == messages[0]
    assert out["messages"][1]["content"][0] == {"type": "text", "text": "장면 설명"}
    assert out["messages"][1]["content"][1]["image_url"]["url"] == tracing.IMAGE_PLACEHOLDER


def test_tracing_stays_off_without_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = Settings(langsmith_tracing=True, langsmith_api_key="")
    monkeypatch.setattr(tracing, "get_settings", lambda: settings)
    assert tracing.setup_tracing() is False
    client = OpenAI(api_key="test")
    assert tracing.traced_client(client) is client


def test_tracing_on_wraps_openai_client(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = Settings(langsmith_tracing=True, langsmith_api_key="lsv2_test")
    monkeypatch.setattr(tracing, "get_settings", lambda: settings)
    create = OpenAI(api_key="test").chat.completions.create
    assert tracing.setup_tracing(project="p") is True
    assert tracing.tracing_enabled()
    wrapped = tracing.traced_client(OpenAI(api_key="test"))
    assert type(wrapped.chat.completions.create) is not type(create)


def test_send_feedback_scores_run(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeLangSmith()
    monkeypatch.setattr(tracing, "_enabled", True)
    monkeypatch.setattr(tracing, "_client", fake)
    run_id = uuid.uuid4()
    tracing.send_feedback(run_id, False, 7)
    tracing.send_feedback(run_id, True, 8)
    assert [(r, k["key"], k["score"]) for r, k in fake.calls] == [
        (run_id, "user_correct", 0),
        (run_id, "user_correct", 1),
    ]
    assert fake.calls[0][1]["comment"] == "movie_id=7"
    assert fake.calls[0][1]["trace_id"] == run_id
    assert all(k["session_id"] == FakeLangSmith.PROJECT_ID for _, k in fake.calls)
    assert fake.project_lookups == 1  # 프로젝트 ID는 한 번만 조회한다


def test_send_feedback_skipped_when_tracing_off(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeLangSmith()
    monkeypatch.setattr(tracing, "_client", fake)  # 꺼져 있으면 클라이언트가 있어도 보내지 않는다
    tracing.send_feedback(uuid.uuid4(), True, 1)
    assert fake.calls == []


def test_send_feedback_failure_is_swallowed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tracing, "_enabled", True)
    monkeypatch.setattr(tracing, "_client", FakeLangSmith(fail=True))
    tracing.send_feedback(uuid.uuid4(), True, 1)  # 예외가 밖으로 나오지 않는다
