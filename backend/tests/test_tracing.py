from collections.abc import Iterator

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
