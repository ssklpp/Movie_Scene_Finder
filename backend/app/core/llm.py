"""모든 LLM·임베딩 호출이 거치는 래퍼 (SPEC §0.3).

호출마다 모델명, 입출력 토큰, USD 비용, 지연시간을 로깅하고 `CallStats`로 돌려준다.
재시도(지수 백오프)와 타임아웃은 OpenAI SDK의 `max_retries`/`timeout`으로 건다.
"""

import logging
import time
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from openai import OpenAI
from openai.types.chat import ChatCompletion, ChatCompletionMessageParam
from pydantic import BaseModel

from app.core.config import get_settings
from app.core.cost import usd_cost

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CallStats:
    model: str
    input_tokens: int
    output_tokens: int
    cost_usd: float
    latency_ms: int


@lru_cache
def get_client() -> OpenAI:
    s = get_settings()
    return OpenAI(
        api_key=s.openai_api_key, timeout=s.http_timeout_s, max_retries=s.http_max_retries
    )


@lru_cache
def get_local_vlm_client() -> OpenAI:
    """로컬 vLLM 서버(OpenAI 호환). 비용 단가가 없으므로 비용은 0으로 기록된다."""
    s = get_settings()
    return OpenAI(
        base_url=s.local_vlm_base_url,
        api_key="local",
        timeout=s.http_timeout_s,
        max_retries=s.http_max_retries,
    )


def _record(model: str, input_tokens: int, output_tokens: int, started: float) -> CallStats:
    stats = CallStats(
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_usd=usd_cost(
            model, input_tokens, output_tokens, get_settings().model_prices_usd_per_1m
        ),
        latency_ms=round((time.perf_counter() - started) * 1000),
    )
    logger.info(
        "llm_call model=%s in=%d out=%d cost_usd=%.6f latency_ms=%d",
        stats.model,
        stats.input_tokens,
        stats.output_tokens,
        stats.cost_usd,
        stats.latency_ms,
    )
    return stats


def chat(
    messages: list[ChatCompletionMessageParam],
    model: str | None = None,
    client: OpenAI | None = None,
    **kwargs: Any,
) -> tuple[ChatCompletion, CallStats]:
    model = model or get_settings().llm_model_default
    started = time.perf_counter()
    resp = (client or get_client()).chat.completions.create(
        model=model, messages=messages, **kwargs
    )
    usage = resp.usage
    stats = _record(
        model,
        usage.prompt_tokens if usage else 0,
        usage.completion_tokens if usage else 0,
        started,
    )
    return resp, stats


def parse[T: BaseModel](
    messages: list[ChatCompletionMessageParam],
    response_format: type[T],
    model: str | None = None,
    client: OpenAI | None = None,
    **kwargs: Any,
) -> tuple[T | None, CallStats]:
    """구조화 출력(JSON 스키마). 모델이 거부하면 None을 돌려준다.

    출력이 스키마에 맞지 않거나 길이 제한에 걸리면 SDK가 예외를 던진다.
    """
    model = model or get_settings().llm_model_default
    started = time.perf_counter()
    resp = (client or get_client()).chat.completions.parse(
        model=model, messages=messages, response_format=response_format, **kwargs
    )
    usage = resp.usage
    stats = _record(
        model,
        usage.prompt_tokens if usage else 0,
        usage.completion_tokens if usage else 0,
        started,
    )
    return resp.choices[0].message.parsed, stats


def embed(
    texts: list[str],
    model: str | None = None,
    client: OpenAI | None = None,
) -> tuple[list[list[float]], CallStats]:
    s = get_settings()
    model = model or s.embed_model
    started = time.perf_counter()
    resp = (client or get_client()).embeddings.create(
        model=model, input=texts, dimensions=s.embed_dim
    )
    stats = _record(model, resp.usage.prompt_tokens, 0, started)
    return [d.embedding for d in resp.data], stats
