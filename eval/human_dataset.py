"""human 골든셋 (SPEC §11): 지인이 쓴 장면 묘사 CSV를 평가용 jsonl로 바꾼다.

    uv run python -m eval.human_dataset export-movies   # 지인에게 보낼 영화 목록 CSV
    uv run python -m eval.human_dataset build           # 입력 CSV → jsonl (제목을 movies와 매칭)

입력 CSV 열: writer, query, title, year(선택), note(선택). 제목은 한국어·영어 제목 모두 받는다.
정답은 SPEC 필드 answer_movie_id(movies.id)와 함께 answer_tmdb_id도 남긴다. movies.id는 DB를
새로 만들면 바뀔 수 있지만 TMDB id는 바뀌지 않는다.
"""

import argparse
import csv
import io
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import select

from app.core.config import REPO_ROOT
from app.db.models import Movie
from app.db.session import SessionLocal

DATASETS_DIR = REPO_ROOT / "eval" / "datasets"
VERSION = "v1"
MOVIE_LIST_PATH = DATASETS_DIR / f"movie_list_{VERSION}.csv"
HUMAN_CSV_PATH = DATASETS_DIR / f"human_{VERSION}.csv"
HUMAN_JSONL_PATH = DATASETS_DIR / f"human_{VERSION}.jsonl"
INPUT_COLUMNS = ["writer", "query", "title", "year", "note"]


@dataclass(frozen=True)
class MovieRef:
    movie_id: int
    tmdb_id: int
    title_ko: str | None
    title_en: str | None
    year: int | None


def normalize_title(title: str) -> str:
    """대소문자, 공백, 문장부호 차이를 무시한다."""
    return re.sub(r"[\W_]+", "", title).lower()


def match_movie(title: str, year: int | None, movies: list[MovieRef]) -> list[MovieRef]:
    """한국어·영어 제목이 같은 영화. 연도를 주면 연도로 한 번 더 거른다."""
    key = normalize_title(title)
    if not key:
        return []
    found = [
        m for m in movies if key in {normalize_title(t) for t in (m.title_ko, m.title_en) if t}
    ]
    if year is not None and len(found) > 1:
        found = [m for m in found if m.year == year]
    return found


def parse_year(value: str) -> int | None:
    value = value.strip()
    return int(value) if value.isdigit() else None


def build_records(
    rows: list[dict[str, str]], movies: list[MovieRef]
) -> tuple[list[dict[str, Any]], list[str]]:
    """(jsonl 레코드, 문제 목록)을 돌려준다.

    묘사나 제목이 비었거나, 제목이 영화 0편 또는 2편 이상과 일치하면 문제로 남긴다.
    """
    records: list[dict[str, Any]] = []
    problems: list[str] = []
    for line_no, row in enumerate(rows, start=2):
        query = (row.get("query") or "").strip()
        title = (row.get("title") or "").strip()
        if not query and not title:
            continue
        if not query or not title:
            problems.append(f"line {line_no}: query와 title이 모두 있어야 합니다")
            continue
        found = match_movie(title, parse_year(row.get("year") or ""), movies)
        if len(found) != 1:
            reason = (
                "목록에 없는 제목" if not found else f"{len(found)}편과 일치(연도를 적어 주세요)"
            )
            problems.append(f"line {line_no}: '{title}' {reason}")
            continue
        movie = found[0]
        records.append(
            {
                "id": f"human-{len(records) + 1:04d}",
                "query": query,
                "image_path": None,
                "answer_movie_id": movie.movie_id,
                "answer_tmdb_id": movie.tmdb_id,
                "source": "human",
                "split": "test",
                "version": VERSION,
                "writer": (row.get("writer") or "").strip() or None,
            }
        )
    return records, problems


def load_movies() -> list[MovieRef]:
    with SessionLocal() as session:
        stmt = select(Movie.id, Movie.tmdb_id, Movie.title_ko, Movie.title_en, Movie.year)
        return [MovieRef(*row) for row in session.execute(stmt.order_by(Movie.id)).all()]


def export_movies(path: Path = MOVIE_LIST_PATH) -> None:
    movies = sorted(load_movies(), key=lambda m: m.title_ko or m.title_en or "")
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["title_ko", "title_en", "year", "tmdb_id"])
        for m in movies:
            writer.writerow([m.title_ko or "", m.title_en or "", m.year or "", m.tmdb_id])
    print(f"{len(movies)} movies -> {path}")


def read_csv_text(path: Path) -> str:
    """UTF-8로 읽고, 실패하면 CP949로 읽는다. 엑셀의 기본 "CSV" 저장은 CP949다."""
    raw = path.read_bytes()
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        return raw.decode("cp949")


def build(csv_path: Path = HUMAN_CSV_PATH, out_path: Path = HUMAN_JSONL_PATH) -> int:
    rows = list(csv.DictReader(io.StringIO(read_csv_text(csv_path), newline="")))
    records, problems = build_records(rows, load_movies())
    with out_path.open("w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"{len(records)} records -> {out_path}")
    for p in problems:
        print(f"  problem: {p}", file=sys.stderr)
    return 1 if problems else 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("export-movies", help="지인에게 보낼 영화 목록 CSV 생성")
    sub.add_parser("build", help="입력 CSV를 jsonl로 변환")
    args = parser.parse_args()
    if args.cmd == "export-movies":
        export_movies()
    else:
        raise SystemExit(build())


if __name__ == "__main__":
    main()
