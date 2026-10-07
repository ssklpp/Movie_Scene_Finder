"""s01: TMDB discover(인기순)로 영화 300편(한국 영화 포함)을 골라 상세 정보를 `movies`에 적재한다.

plot_ko는 TMDB 한국어 overview다. KMDB_API_KEY가 있으면 KMDb에서 같은 영화를 찾아
한국어 줄거리(plot_kmdb)와 키워드(keywords_ko)를 보강하고,
매칭 결과를 `reports/kmdb_match.csv`에 쓴다.
"""

import argparse
import csv
import logging
from collections.abc import Iterable, Sequence
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert

from app.core.config import REPO_ROOT, get_settings
from app.core.logging import setup_logging
from app.db.models import Movie
from app.db.session import SessionLocal
from pipeline.common.kmdb import KmdbClient, clean_title, keywords, korean_plot, pick_match
from pipeline.common.state import State
from pipeline.common.tmdb import IMAGE_BASE_URL, TmdbClient

logger = logging.getLogger(__name__)

STEP = "s01"
KMDB_STEP = "s01_kmdb"
KMDB_REPORT = REPO_ROOT / "reports" / "kmdb_match.csv"
ANIMATION_GENRE_ID = 16
GLOBAL_FILTERS = {"sort_by": "popularity.desc", "vote_count.gte": 1000}
KR_FILTERS = {"sort_by": "popularity.desc", "vote_count.gte": 100, "with_origin_country": "KR"}


def merge_candidates(kr_ids: Sequence[int], global_ids: Iterable[int], total: int) -> list[int]:
    """한국 영화 전부 + 전체 인기순으로 `total`편을 채운다. 중복은 한 번만.

    앞 N편만 잘라도(`--limit`) 한국 영화 비율이 유지되도록 두 목록을 비율대로 섞어 배치한다.
    """
    kr = list(dict.fromkeys(kr_ids))[:total]
    kr_set = set(kr)
    rest = [i for i in dict.fromkeys(global_ids) if i not in kr_set][: total - len(kr)]
    n = len(kr) + len(rest)
    merged: list[int] = []
    ki = ri = 0
    for pos in range(1, n + 1):
        # pos편까지 한국 영화가 round(pos * 비율)편이 되도록 고른다.
        if ki < len(kr) and (ri == len(rest) or ki < round(pos * len(kr) / n)):
            merged.append(kr[ki])
            ki += 1
        else:
            merged.append(rest[ri])
            ri += 1
    return merged


def to_movie_row(detail: dict[str, Any]) -> dict[str, Any]:
    """TMDB 상세 응답(ko-KR + translations)을 `movies` 행으로 바꾼다."""
    en_titles = [
        t["data"].get("title")
        for t in detail.get("translations", {}).get("translations", [])
        if t.get("iso_639_1") == "en" and t.get("data", {}).get("title")
    ]
    title_en = en_titles[0] if en_titles else None
    if title_en is None and detail.get("original_language") == "en":
        title_en = detail.get("original_title")

    countries = detail.get("origin_country") or [
        c["iso_3166_1"] for c in detail.get("production_countries", [])
    ]
    release_date = detail.get("release_date") or ""
    poster_path = detail.get("poster_path")
    genres = detail.get("genres", [])

    return {
        "tmdb_id": detail["id"],
        "title_ko": detail.get("title") or None,
        "title_en": title_en,
        "year": int(release_date[:4]) if release_date[:4].isdigit() else None,
        "country": countries[0] if countries else None,
        "genres": [g["name"] for g in genres],
        "is_animation": any(g["id"] == ANIMATION_GENRE_ID for g in genres),
        "plot_ko": detail.get("overview") or None,
        "poster_url": f"{IMAGE_BASE_URL}/w500{poster_path}" if poster_path else None,
    }


def discover_ids(tmdb: TmdbClient, filters: dict[str, Any], count: int) -> list[int]:
    ids: list[int] = []
    page = 1
    while len(ids) < count:
        data = tmdb.discover(page, **filters)
        ids.extend(m["id"] for m in data["results"])
        if page >= data["total_pages"]:
            break
        page += 1
    return ids[:count]


def upsert_movie(row: dict[str, Any]) -> None:
    stmt = insert(Movie).values(**row)
    stmt = stmt.on_conflict_do_update(
        index_elements=[Movie.tmdb_id],
        set_={k: stmt.excluded[k] for k in row if k != "tmdb_id"},
    )
    with SessionLocal.begin() as session:
        session.execute(stmt)


def find_kmdb(kmdb: KmdbClient, movie: Movie) -> dict[str, Any] | None:
    """한국어 제목 → 같은 제목 + 제작연도 ±1 → 영어 제목 순으로 찾는다.

    "괴물", "업"처럼 짧은 제목은 결과가 많아 연도 조건 없이는 20건 안에 들지 않는다.
    """
    args = (movie.title_ko, movie.title_en, movie.year, movie.country)
    if movie.title_ko:
        match = pick_match(kmdb.search(title=movie.title_ko), *args)
        if match is None and movie.year is not None:
            results = kmdb.search(
                title=movie.title_ko, createDts=movie.year - 1, createDte=movie.year + 1
            )
            match = pick_match(results, *args)
        if match:
            return match
    if movie.title_en:
        return pick_match(kmdb.search(titleEng=movie.title_en), *args)
    return None


def kmdb_values(match: dict[str, Any] | None) -> dict[str, Any]:
    if match is None:
        return {"kmdb_id": None, "plot_kmdb": None, "keywords_ko": None}
    return {
        "kmdb_id": match.get("DOCID") or None,
        "plot_kmdb": korean_plot(match),
        "keywords_ko": keywords(match) or None,
    }


def write_report(rows: list[dict[str, Any]]) -> None:
    """이번에 처리한 행으로 기존 리포트의 같은 영화 행을 바꾼다(건너뛴 영화의 행은 남는다)."""
    merged: dict[str, dict[str, Any]] = {}
    if KMDB_REPORT.exists():
        with KMDB_REPORT.open(encoding="utf-8") as f:
            merged = {r["tmdb_id"]: r for r in csv.DictReader(f)}
    merged.update({str(r["tmdb_id"]): r for r in rows})
    KMDB_REPORT.parent.mkdir(parents=True, exist_ok=True)
    with KMDB_REPORT.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(merged.values())


def enrich_kmdb(kmdb: KmdbClient, state: State, tmdb_ids: Sequence[int], force: bool) -> None:
    """KMDb 줄거리·키워드를 `movies`에 채운다. 매칭되지 않은 영화도 처리한 것으로 기록한다."""
    order = {tmdb_id: i for i, tmdb_id in enumerate(tmdb_ids)}
    with SessionLocal() as session:
        movies = session.scalars(select(Movie).where(Movie.tmdb_id.in_(tmdb_ids))).all()
    rows: list[dict[str, Any]] = []
    skipped = matched = 0
    for movie in sorted(movies, key=lambda m: order[m.tmdb_id]):
        if not force and state.is_done(KMDB_STEP, str(movie.tmdb_id)):
            skipped += 1
            continue
        match = find_kmdb(kmdb, movie)
        values = kmdb_values(match)
        with SessionLocal.begin() as session:
            session.execute(update(Movie).where(Movie.id == movie.id).values(**values))
        state.mark_done(KMDB_STEP, str(movie.tmdb_id))
        matched += match is not None
        rows.append(
            {
                "tmdb_id": movie.tmdb_id,
                "title_ko": movie.title_ko,
                "year": movie.year,
                "country": movie.country,
                "kmdb_id": values["kmdb_id"] or "",
                "kmdb_title": clean_title(match.get("title", "")) if match else "",
                "kmdb_year": match.get("prodYear", "") if match else "",
                "kmdb_nation": match.get("nation", "") if match else "",
                "tmdb_plot_len": len(movie.plot_ko or ""),
                "kmdb_plot_len": len(values["plot_kmdb"] or ""),
                "n_keywords": len(values["keywords_ko"] or []),
            }
        )
    if rows:
        write_report(rows)
    logger.info("s01 kmdb done: processed=%d matched=%d skipped=%d", len(rows), matched, skipped)


def run_kmdb(state: State, tmdb_ids: Sequence[int], force: bool) -> None:
    settings = get_settings()
    if not settings.kmdb_api_key:
        logger.warning("KMDB_API_KEY is empty; skipping KMDb enrichment")
        return
    kmdb = KmdbClient(settings.kmdb_api_key, settings.http_timeout_s)
    try:
        enrich_kmdb(kmdb, state, tmdb_ids, force)
    finally:
        kmdb.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, help="후보 목록 앞 N편만 처리 (재실행해도 같은 N편)")
    parser.add_argument("--force", action="store_true", help="이미 처리한 영화도 다시 수집")
    parser.add_argument("--force-kmdb", action="store_true", help="KMDb 보강만 다시 수행")
    parser.add_argument("--total", type=int, default=300, help="수집 대상 전체 편수")
    parser.add_argument("--kr-count", type=int, default=60, help="그중 한국 영화 편수")
    parser.add_argument(
        "--kmdb-only",
        action="store_true",
        help="TMDB 수집 없이 DB에 있는 영화만 KMDb로 보강 (인기순이 바뀌어도 카탈로그 유지)",
    )
    args = parser.parse_args()
    setup_logging()

    settings = get_settings()
    state = State()
    if args.kmdb_only:
        with SessionLocal() as session:
            candidates = list(session.scalars(select(Movie.tmdb_id).order_by(Movie.id)))
        if args.limit is not None:
            candidates = candidates[: args.limit]
        try:
            run_kmdb(state, candidates, args.force or args.force_kmdb)
        finally:
            state.close()
        return

    tmdb = TmdbClient(settings.tmdb_read_token, settings.http_timeout_s)
    try:
        kr_ids = discover_ids(tmdb, KR_FILTERS, args.kr_count)
        global_ids = discover_ids(tmdb, GLOBAL_FILTERS, args.total)
        candidates = merge_candidates(kr_ids, global_ids, args.total)
        logger.info("candidates: %d (KR %d)", len(candidates), len(kr_ids))
        if args.limit is not None:
            candidates = candidates[: args.limit]

        processed = skipped = 0
        for tmdb_id in candidates:
            if not args.force and state.is_done(STEP, str(tmdb_id)):
                skipped += 1
                continue
            upsert_movie(to_movie_row(tmdb.movie_detail(tmdb_id)))
            state.mark_done(STEP, str(tmdb_id))
            processed += 1
        logger.info("s01 done: processed=%d skipped=%d", processed, skipped)

        run_kmdb(state, candidates, args.force or args.force_kmdb)
    finally:
        tmdb.close()
        state.close()


if __name__ == "__main__":
    main()
