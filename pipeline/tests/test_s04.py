from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from openai import OpenAI

from app.core.config import Settings
from app.search.caption import (
    PROMPT_VERSION,
    SYSTEM_PROMPT,
    People,
    SceneCaption,
    build_messages,
)
from pipeline.s02_collect_images import IMAGES_DIR
from pipeline.s04_caption import (
    SceneJob,
    backend_config,
    caption_one,
    scene_image_path,
    to_scene_values,
)

CAPTION = SceneCaption(
    caption_ko="비 오는 밤 골목에서 우산을 쓴 남자가 네온사인 아래를 걸어간다.",
    caption_en="A man with an umbrella walks under neon signs in a rainy alley at night.",
    setting="비 오는 골목",
    time_of_day="night",
    weather="비",
    people=People(count=1, actions=["우산을 쓰고 걷는다"]),
    objects=["우산", "네온사인"],
    colors=["파란색", "분홍색"],
    text_in_frame=None,
)


def test_system_prompt_forbids_names_and_titles() -> None:
    assert "이름" in SYSTEM_PROMPT and "절대 쓰지 않는다" in SYSTEM_PROMPT
    assert "영화 제목" in SYSTEM_PROMPT


def test_scene_image_path() -> None:
    assert scene_image_path("496243_backdrop_7", 496243) == IMAGES_DIR / "496243/backdrop_07.jpg"


def test_build_messages_embeds_image_as_data_url() -> None:
    messages = build_messages(b"\xff\xd8jpeg")
    user_content = cast(list[dict[str, Any]], messages[1]["content"])
    assert user_content[0]["image_url"]["url"] == "data:image/jpeg;base64,/9hqcGVn"


def test_to_scene_values_splits_captions_and_tags() -> None:
    values = to_scene_values(CAPTION, "v1")
    assert values["caption_ko"] == CAPTION.caption_ko
    assert values["model_version"] == "v1"
    assert set(values["tags"]) == {
        "setting",
        "time_of_day",
        "weather",
        "people",
        "objects",
        "colors",
        "text_in_frame",
    }
    assert values["tags"]["people"] == {"count": 1, "actions": ["우산을 쓰고 걷는다"]}


def test_backend_config_versions_and_request_options() -> None:
    local = backend_config(
        Settings(
            caption_backend="local", local_vlm_model="qwen-awq", caption_model_version="qwen-v1"
        )
    )
    assert (local.model, local.model_version) == ("qwen-awq", "qwen-v1")
    assert "temperature" in local.request_kwargs
    remote = backend_config(Settings(caption_backend="openai", llm_model_default="luna"))
    assert (remote.model, remote.model_version) == ("luna", f"luna-{PROMPT_VERSION}")
    # 추론 모델: max_tokens·temperature를 거부하므로 쓰지 않는다
    assert remote.request_kwargs["reasoning_effort"] == "low"
    assert "max_tokens" not in remote.request_kwargs
    assert "temperature" not in remote.request_kwargs
    with pytest.raises(SystemExit):
        backend_config(Settings(caption_backend="openai_batch"))


class _FakeCompletions:
    def __init__(self, parsed: SceneCaption | None, error: Exception | None = None) -> None:
        self.parsed = parsed
        self.error = error

    def parse(self, **kwargs: Any) -> Any:
        if self.error:
            raise self.error
        message = SimpleNamespace(parsed=self.parsed)
        usage = SimpleNamespace(prompt_tokens=900, completion_tokens=120)
        return SimpleNamespace(choices=[SimpleNamespace(message=message)], usage=usage)


def _client(completions: _FakeCompletions) -> OpenAI:
    return cast(OpenAI, SimpleNamespace(chat=SimpleNamespace(completions=completions)))


def test_caption_one_success_refusal_and_error(tmp_path: Path) -> None:
    img = tmp_path / "x.jpg"
    img.write_bytes(b"jpeg")
    job = SceneJob("1_backdrop_0", img)

    ok = caption_one(job, "m", _client(_FakeCompletions(CAPTION)), {})
    assert ok.caption == CAPTION and ok.error is None and ok.stats is not None
    assert ok.stats.input_tokens == 900

    refused = caption_one(job, "m", _client(_FakeCompletions(None)), {})
    assert refused.caption is None and refused.error == "refused"

    broken = caption_one(job, "m", _client(_FakeCompletions(None, ValueError("bad json"))), {})
    assert broken.caption is None and broken.error == "ValueError: bad json"
