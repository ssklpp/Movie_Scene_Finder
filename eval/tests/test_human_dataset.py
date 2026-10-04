from pathlib import Path

from eval.human_dataset import (
    MovieRef,
    build_records,
    match_movie,
    normalize_title,
    read_csv_text,
)

MOVIES = [
    MovieRef(1, 496243, "기생충", "Parasite", 2019),
    MovieRef(2, 27205, "인셉션", "Inception", 2010),
    MovieRef(3, 100, "리틀 위민", "Little Women", 1994),
    MovieRef(4, 101, "작은 아씨들", "Little Women", 2019),
]


def test_read_csv_text_accepts_utf8_bom_and_cp949(tmp_path: Path) -> None:
    text = "writer,query,title\nTW,반지하 장면,기생충\n"
    (tmp_path / "utf8.csv").write_bytes(text.encode("utf-8-sig"))
    (tmp_path / "cp949.csv").write_bytes(text.encode("cp949"))
    assert read_csv_text(tmp_path / "utf8.csv") == text
    assert read_csv_text(tmp_path / "cp949.csv") == text


def test_normalize_title_ignores_case_space_punctuation() -> None:
    assert normalize_title("Spider-Man: No Way Home") == normalize_title("spiderman no way home")
    assert normalize_title("기 생 충") == "기생충"


def test_match_movie_by_korean_or_english_title() -> None:
    assert match_movie("기생충", None, MOVIES) == [MOVIES[0]]
    assert match_movie("inception", None, MOVIES) == [MOVIES[1]]
    assert match_movie("타이타닉", None, MOVIES) == []
    assert match_movie("  ", None, MOVIES) == []


def test_match_movie_uses_year_only_to_break_ties() -> None:
    assert len(match_movie("Little Women", None, MOVIES)) == 2
    assert match_movie("Little Women", 2019, MOVIES) == [MOVIES[3]]
    assert match_movie("기생충", 1999, MOVIES) == [MOVIES[0]]


def test_build_records_format_and_problems() -> None:
    rows = [
        {"writer": "A", "query": "반지하 집에 물이 차오르는 장면", "title": "기생충", "year": ""},
        {"writer": "B", "query": "꿈속에서 도시가 접힌다", "title": "Inception", "year": "2010"},
        {"writer": "C", "query": "", "title": "", "year": ""},
        {"writer": "D", "query": "자매들이 다락방에서 연극", "title": "Little Women", "year": ""},
        {"writer": "E", "query": "배 앞에서 팔을 벌린다", "title": "타이타닉", "year": ""},
        {"writer": "F", "query": "제목만 빠짐", "title": "", "year": ""},
    ]
    records, problems = build_records(rows, MOVIES)
    assert records == [
        {
            "id": "human-0001",
            "query": "반지하 집에 물이 차오르는 장면",
            "image_path": None,
            "answer_movie_id": 1,
            "answer_tmdb_id": 496243,
            "source": "human",
            "split": "test",
            "version": "v1",
            "writer": "A",
        },
        {
            "id": "human-0002",
            "query": "꿈속에서 도시가 접힌다",
            "image_path": None,
            "answer_movie_id": 2,
            "answer_tmdb_id": 27205,
            "source": "human",
            "split": "test",
            "version": "v1",
            "writer": "B",
        },
    ]
    assert len(problems) == 3
    assert "line 5" in problems[0] and "2편과 일치" in problems[0]
    assert "line 6" in problems[1] and "목록에 없는 제목" in problems[1]
    assert "line 7" in problems[2]
