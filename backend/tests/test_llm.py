from types import SimpleNamespace
from typing import Any, cast

import pytest
from openai import OpenAI

from app.core import llm
from app.core.config import get_settings
from app.core.cost import usd_cost


def test_usd_cost() -> None:
    prices = {"m": (1.0, 4.0)}
    assert usd_cost("m", 1_000_000, 500_000, prices) == pytest.approx(3.0)


def test_usd_cost_unknown_model_is_zero() -> None:
    assert usd_cost("unknown", 1000, 1000, {}) == 0.0


class _FakeChat:
    def create(self, **kwargs: Any) -> Any:
        self.kwargs = kwargs
        usage = SimpleNamespace(prompt_tokens=200, completion_tokens=100)
        return SimpleNamespace(usage=usage, choices=[])


class _FakeEmbeddings:
    def create(self, **kwargs: Any) -> Any:
        self.kwargs = kwargs
        data = [SimpleNamespace(embedding=[0.1, 0.2]) for _ in kwargs["input"]]
        return SimpleNamespace(usage=SimpleNamespace(prompt_tokens=10), data=data)


def _fake_client() -> OpenAI:
    fake = SimpleNamespace(
        chat=SimpleNamespace(completions=_FakeChat()), embeddings=_FakeEmbeddings()
    )
    return cast(OpenAI, fake)


@pytest.fixture(autouse=True)
def _prices(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        get_settings(), "model_prices_usd_per_1m", {"chat-m": (1.0, 2.0), "emb-m": (0.5, 0.0)}
    )


def test_chat_records_tokens_and_cost(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level("INFO")
    _, stats = llm.chat([{"role": "user", "content": "hi"}], model="chat-m", client=_fake_client())
    assert (stats.model, stats.input_tokens, stats.output_tokens) == ("chat-m", 200, 100)
    assert stats.cost_usd == pytest.approx((200 * 1.0 + 100 * 2.0) / 1_000_000)
    assert stats.latency_ms >= 0
    assert "llm_call model=chat-m" in caplog.text


def test_embed_returns_vectors_and_cost() -> None:
    vectors, stats = llm.embed(["a", "b"], model="emb-m", client=_fake_client())
    assert vectors == [[0.1, 0.2], [0.1, 0.2]]
    assert stats.input_tokens == 10
    assert stats.cost_usd == pytest.approx(10 * 0.5 / 1_000_000)
