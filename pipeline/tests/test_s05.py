from pathlib import Path

import pytest

from app.search.caption import People, SceneCaption
from pipeline.s05_validate import (
    SceneRow,
    caption_problems,
    forbidden_words,
    stored_caption,
    windows_path,
)

GOOD = SceneCaption(
    caption_ko="비 오는 밤 반지하 창문 너머로 소독 연기가 퍼지고 가족이 피자 상자를 접는다.",
    caption_en="On a rainy night, a family folds pizza boxes on the floor of a semi-basement.",
    setting="반지하 집",
    time_of_day="night",
    weather="비",
    people=People(count=4, actions=["피자 상자를 접는다"]),
    objects=["피자 상자"],
    colors=["초록색"],
    text_in_frame=None,
)


def _row(**kw: object) -> SceneRow:
    base: dict[str, object] = {
        "scene_id": "496243_backdrop_0",
        "tmdb_id": 496243,
        "title_ko": "기생충",
        "title_en": "Parasite",
        "caption_ko": GOOD.caption_ko,
        "caption_en": GOOD.caption_en,
        "tags": GOOD.model_dump(exclude={"caption_ko", "caption_en"}),
        "model_version": "v1",
    }
    base.update(kw)
    return SceneRow(**base)  # type: ignore[arg-type]


def test_stored_caption_roundtrip_missing_and_schema_error() -> None:
    assert stored_caption(_row()) == GOOD
    assert stored_caption(_row(caption_ko=None)) == "missing caption"
    bad_tags = {**GOOD.model_dump(exclude={"caption_ko", "caption_en"}), "time_of_day": "noon"}
    result = stored_caption(_row(tags=bad_tags))
    assert isinstance(result, str) and result.startswith("schema:")


def test_forbidden_words_titles_names_and_parts() -> None:
    words = forbidden_words("기생충", "Up", ["송강호", "레오나르도 디카프리오", "톰 하디"])
    assert {"기생충", "송강호", "레오나르도 디카프리오", "레오나르도", "디카프리오"} <= set(words)
    assert "Up" not in words  # 짧은 영어 제목은 제외
    assert "하디" not in words  # 2글자 부분은 제외
    assert "Parasite" in forbidden_words(None, "Parasite", [])
    assert "비" not in forbidden_words(None, None, ["비"])  # 한 글자 예명은 날씨 "비"와 겹친다


def test_caption_problems_good_caption_passes() -> None:
    assert caption_problems(GOOD, ["송강호", "Parasite"]) == []


@pytest.mark.parametrize(
    ("caption_ko", "caption_en", "expected"),
    [
        (
            "송강호가 반지하 창가에서 소독 연기를 바라보며 웃고 가족이 둘러앉아 있다.",
            "x",
            "name/title: 송강호",
        ),
        (GOOD.caption_ko, "A scene from Parasite.", "name/title: Parasite"),
        ("짧은 캡션", "x", "length 5"),
        (
            "A family folds pizza boxes on the floor of a semi-basement on a rainy night.",
            "x",
            "caption_ko not Korean",
        ),
    ],
)
def test_caption_problems_detects_rule_violations(
    caption_ko: str, caption_en: str, expected: str
) -> None:
    cap = GOOD.model_copy(update={"caption_ko": caption_ko, "caption_en": caption_en})
    assert expected in caption_problems(cap, ["송강호", "Parasite"])


def test_caption_problems_ignores_english_word_containing_title() -> None:
    cap = GOOD.model_copy(update={"caption_en": "A hopeful family folds pizza boxes at night."})
    assert caption_problems(cap, ["Hope"]) == []


def test_windows_path(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WSL_DISTRO_NAME", "Ubuntu")
    assert windows_path(Path("/home/user/a.jpg")) == r"\\wsl.localhost\Ubuntu\home\user\a.jpg"
