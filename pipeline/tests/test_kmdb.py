from typing import Any

from pipeline.common.kmdb import clean_title, keywords, korean_plot, norm_title, pick_match
from pipeline.s01_collect_meta import kmdb_values


def _result(title: str, year: str, nation: str = "미국", **extra: Any) -> dict[str, Any]:
    return {"DOCID": "K1", "title": title, "prodYear": year, "nation": nation, **extra}


JSA = _result(
    "  !HS 공동경비구역 !HE  J.S.A",
    "2000",
    "대한민국",
    titleEng="Joint Security Area (Gongdonggyeongbiguyeok)",
    titleEtc="공동경비구역J.S.A^공동경비구역 JSA^Joint Security Area (Gongdonggyeongbiguyeok)",
    repRlsDate="20000908",
    plots={
        "plot": [
            {"plotLang": "영어", "plotText": "At dawn..."},
            {"plotLang": "한국어", "plotText": " 10월 28일 새벽, 판문점에서 "},
        ]
    },
    keywords="남북분단,판문점, 판문점,,사진",
)


def test_clean_and_norm_title() -> None:
    assert clean_title("!HS 쇼생크 !HE   !HS 탈출 !HE") == "쇼생크 탈출"
    assert norm_title("!HS 어벤져스: !HE   !HS 엔드게임 !HE") == norm_title("어벤져스: 엔드게임")
    assert norm_title("Avengers: Endgame") == "avengersendgame"


def test_plot_and_keywords() -> None:
    assert korean_plot(JSA) == "10월 28일 새벽, 판문점에서"
    assert korean_plot(_result("x", "2000")) is None
    assert keywords(JSA) == ["남북분단", "판문점", "사진"]
    assert keywords(_result("x", "2000")) == []


def test_pick_match_uses_alt_titles_and_english() -> None:
    assert pick_match([JSA], "공동경비구역 JSA", None, 2000, "KR") is JSA
    assert pick_match([JSA], None, "Joint Security Area", 2000, "KR") is JSA


def test_pick_match_year_tolerance() -> None:
    goksung = _result("!HS 곡성 !HE", "2015", "대한민국", repRlsDate="20160512")
    assert pick_match([goksung], "곡성", None, 2016, "KR") is goksung
    assert pick_match([goksung], "곡성", None, 2018, "KR") is None


def test_pick_match_rejects_same_title_other_movie() -> None:
    japanese = _result("파라노말 !HS 기생충 !HE", "2018", "일본")
    same_title_jp = _result("!HS 기생충 !HE", "2019", "일본")
    korean = _result("!HS 기생충 !HE", "2019", "대한민국")
    assert pick_match([japanese, same_title_jp, korean], "기생충", "Parasite", 2019, "KR") is korean
    assert pick_match([japanese, same_title_jp], "기생충", "Parasite", 2019, "KR") is None


def test_pick_match_rejects_korean_only_for_foreign_movie() -> None:
    korean_x = _result("X (엑스)", "2023", "대한민국", titleEng="X")
    us_x = _result("엑스", "2022", "미국", titleEng="X")
    assert pick_match([korean_x], "X", "X", 2022, "US") is None
    assert pick_match([korean_x, us_x], "X", "X", 2022, "US") is us_x
    coproduction = _result("!HS 킹 오브 킹스 !HE", "2025", "대한민국,미국")
    assert pick_match([coproduction], "킹 오브 킹스", None, 2025, "KR") is coproduction


def test_pick_match_skips_short_footage_and_matches_volume() -> None:
    footage = _result(
        "가디언즈 오브 갤럭시 : Volume 3 풋티지",
        "2023",
        titleEng="Guardians of the Galaxy Vol. 3",
        runtime="20",
    )
    feature = _result(
        "가디언즈 오브 갤럭시 : Volume 3",
        "2023",
        titleEng="Guardians of the Galaxy Volume 3",
        runtime="150",
    )
    args = ("가디언즈 오브 갤럭시 Vol. 3", "Guardians of the Galaxy Vol. 3", 2023, "US")
    assert pick_match([footage, feature], *args) is feature
    assert pick_match([footage], *args) is None


def test_pick_match_prefers_closest_year() -> None:
    old = _result("!HS 쉘터 !HE", "2014")
    new = _result("!HS 쉘터 !HE", "2015")
    assert pick_match([old, new], "쉘터", "Shelter", 2015, "GB") is new


def test_pick_match_needs_title_and_year() -> None:
    assert pick_match([JSA], None, None, 2000, "KR") is None
    assert pick_match([JSA], "공동경비구역 JSA", None, None, "KR") is None


def test_kmdb_values() -> None:
    assert kmdb_values(None) == {"kmdb_id": None, "plot_kmdb": None, "keywords_ko": None}
    assert kmdb_values(_result("x", "2000")) == {
        "kmdb_id": "K1",
        "plot_kmdb": None,
        "keywords_ko": None,
    }
