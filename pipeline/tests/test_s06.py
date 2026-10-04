from pipeline.s06_build_docs import build_search_text, decade_label

TAGS = {
    "setting": "반지하 집",
    "time_of_day": "night",
    "objects": ["피자 상자", " ", "휴대폰"],
    "text_in_frame": "기생충",
}


def test_decade_label() -> None:
    assert decade_label(2019) == "2010년대"
    assert decade_label(2000) == "2000년대"
    assert decade_label(1957) == "1950년대"
    assert decade_label(None) is None


def test_build_search_text_spec_fields_in_order() -> None:
    text = build_search_text("가족이 피자 상자를 접는다.", TAGS, ["코미디", "드라마"], 2019)
    assert text == (
        "가족이 피자 상자를 접는다.\n"
        "장소: 반지하 집\n"
        "물건: 피자 상자, 휴대폰\n"
        "장르: 코미디, 드라마\n"
        "연대: 2010년대"
    )


def test_build_search_text_excludes_text_in_frame_and_title() -> None:
    # text_in_frame에 제목 로고가 있어도 검색 문서에는 들어가지 않는다
    assert "기생충" not in build_search_text("가족이 피자 상자를 접는다.", TAGS, None, None)


def test_build_search_text_skips_missing_fields() -> None:
    assert build_search_text(" 캡션 ", {}, [], None) == "캡션"


def test_build_search_text_adds_english_caption_after_korean() -> None:
    text = build_search_text("가족이 피자 상자를 접는다.", {}, None, None, " A family. ")
    assert text == "가족이 피자 상자를 접는다.\nA family."
    # 영어 캡션이 비어 있으면 한국어만
    assert build_search_text("캡션", {}, None, None, "  ") == "캡션"
