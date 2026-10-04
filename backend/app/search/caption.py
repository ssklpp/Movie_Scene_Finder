"""장면 캡션 스키마와 프롬프트 (SPEC §5.3).

색인(pipeline s04)과 이미지 질의(에이전트 analyze_input)가 같은 프롬프트를 써야 검색이 맞는다.
프롬프트를 바꾸면 PROMPT_VERSION을 올리고 s04를 다시 돌린다.
"""

import base64
from typing import Any, Literal

from openai.types.chat import ChatCompletionMessageParam
from pydantic import BaseModel

PROMPT_VERSION = "p1"

# gpt-6-luna(추론 모델) 요청 옵션. temperature 대신 reasoning_effort(SPEC: low)를 쓰고,
# 출력 한도에는 추론 토큰이 포함된다(100장 실측 평균 출력 254토큰).
OPENAI_CAPTION_KWARGS: dict[str, Any] = {"reasoning_effort": "low", "max_completion_tokens": 1200}

SYSTEM_PROMPT = """너는 영화 장면 이미지를 검색용으로 묘사한다.
사람들이 나중에 흐릿한 기억으로 이 장면을 찾는다.

규칙:
- 화면에 실제로 보이는 것만 쓴다. 줄거리나 보이지 않는 사건을 추측하지 않는다.
- 배우, 등장인물, 실존 인물의 이름과 영화 제목은 절대 쓰지 않는다. 알아보더라도 쓰지 않는다.
  인물은 "젊은 남자", "단발머리 소녀", "초록색 거인"처럼 겉모습으로 부른다.
- caption_ko: 자연스러운 한국어 한 문장, 40~120자.
  장소, 인물의 행동, 눈에 띄는 물건과 분위기를 담는다.
- caption_en: caption_ko와 같은 내용의 영어 한 문장.
- setting: 장소를 짧은 한국어로 (예: "비 오는 골목", "우주선 조종실").
- time_of_day: day, night, dawn, dusk 중 하나. 알 수 없으면 unknown.
- weather: 날씨가 보이면 짧은 한국어 (예: "비", "눈보라"), 실내이거나 알 수 없으면 null.
- people.count: 보이는 사람(또는 사람처럼 행동하는 캐릭터) 수.
  people.actions: 행동을 짧은 한국어 구로.
- objects: 눈에 띄는 물건 최대 8개, 한국어 명사.
- colors: 화면의 주요 색 최대 4개, 한국어.
- text_in_frame: 화면에 적힌 글자를 그대로. 없으면 null."""

USER_PROMPT = "이 영화 장면을 규칙에 맞춰 JSON으로 묘사해."


class People(BaseModel):
    count: int
    actions: list[str]


class SceneCaption(BaseModel):
    caption_ko: str  # 한 문장, 40~120자, 인물 이름 금지
    caption_en: str
    setting: str
    time_of_day: Literal["day", "night", "dawn", "dusk", "unknown"]
    weather: str | None
    people: People
    objects: list[str]
    colors: list[str]
    text_in_frame: str | None


def build_messages(
    image_bytes: bytes, mime: str = "image/jpeg"
) -> list[ChatCompletionMessageParam]:
    b64 = base64.b64encode(image_bytes).decode()
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": [
                {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
                {"type": "text", "text": USER_PROMPT},
            ],
        },
    ]
