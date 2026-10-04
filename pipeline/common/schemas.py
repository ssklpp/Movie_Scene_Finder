"""파이프라인 공용 스키마."""

from typing import Literal

from pydantic import BaseModel


class People(BaseModel):
    count: int
    actions: list[str]


class SceneCaption(BaseModel):
    """VLM 장면 캡션 (SPEC §5.3)."""

    caption_ko: str  # 한 문장, 40~120자, 인물 이름 금지
    caption_en: str
    setting: str
    time_of_day: Literal["day", "night", "dawn", "dusk", "unknown"]
    weather: str | None
    people: People
    objects: list[str]
    colors: list[str]
    text_in_frame: str | None
