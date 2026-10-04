"""s05: 저장된 캡션을 검증하고, 실패한 장면은 다시 캡셔닝(최대 2회)한 뒤 검수용 표본을 만든다.

검증 항목: 캡션 존재·현재 model_version, `SceneCaption` 스키마, caption_ko 40~120자,
그 영화의 제목·주요 배우·감독 이름이 캡션에 없는지(SPEC §0.10).

출력:
- reports/caption_failures.csv: 재시도 후에도 실패한 장면
- reports/caption_review.csv: 무작위 50장 검수 양식(환각·홍보 이미지 여부를 사람이 적는다)
- reports/caption_review.html: 같은 50장을 이미지와 함께 보는 페이지
"""

import argparse
import base64
import csv
import html
import io
import json
import logging
import os
import random
import re
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from PIL import Image
from pydantic import ValidationError
from sqlalchemy import select

from app.core.config import REPO_ROOT, get_settings
from app.core.logging import setup_logging
from app.db.models import Movie, Scene
from app.db.session import SessionLocal
from app.search.caption import SceneCaption
from pipeline.build_user_dict import CREDITS_DIR, credit_names, name_words
from pipeline.common.state import State
from pipeline.s04_caption import STEP as S04_STEP
from pipeline.s04_caption import (
    SceneJob,
    backend_config,
    caption_one,
    save_caption,
    scene_image_path,
    to_scene_values,
)

logger = logging.getLogger(__name__)

REPORTS_DIR = REPO_ROOT / "reports"
FAILURES_PATH = REPORTS_DIR / "caption_failures.csv"
REVIEW_CSV_PATH = REPORTS_DIR / "caption_review.csv"
REVIEW_HTML_PATH = REPORTS_DIR / "caption_review.html"
MIN_LEN, MAX_LEN = 40, 120


@dataclass
class SceneRow:
    scene_id: str
    tmdb_id: int
    title_ko: str | None
    title_en: str | None
    caption_ko: str | None
    caption_en: str | None
    tags: dict[str, Any] | None
    model_version: str | None
    problems: list[str] = field(default_factory=list)


def stored_caption(row: SceneRow) -> SceneCaption | str:
    """DB에 저장된 값을 SceneCaption으로 되살린다. 실패하면 문제 설명을 돌려준다."""
    if not row.caption_ko or row.tags is None:
        return "missing caption"
    try:
        return SceneCaption.model_validate(
            {**row.tags, "caption_ko": row.caption_ko, "caption_en": row.caption_en}
        )
    except ValidationError as e:
        return f"schema: {e.error_count()} errors ({e.errors()[0]['loc']})"


def forbidden_words(title_ko: str | None, title_en: str | None, names: Iterable[str]) -> list[str]:
    """캡션에 나오면 안 되는 그 영화의 제목과 인물 이름.

    이름은 2글자 이상인 전체 이름과 3글자 이상 부분(예명 "비"나 2글자 부분은 일반 단어와
    너무 자주 겹친다). 영어 제목은 4글자 이상만("Up"은 일반 단어와 구분할 수 없다).
    "마이크"(이름 일부 vs 마이크), "Alien"(제목 vs 외계인)처럼 일반 단어와 같은 경우는 여전히
    걸리며, 실패 목록에서 사람이 확인한다.
    """
    words: set[str] = set()
    if title_ko and len(title_ko) >= 2:
        words.add(title_ko)
    if title_en and len(title_en) >= 4:
        words.add(title_en)
    for name in names:
        if len(name) >= 2:
            words.add(name)
        words.update(part for part in name_words(name) if len(part) >= 3)
    return sorted(words)


def caption_problems(caption: SceneCaption, forbidden: list[str]) -> list[str]:
    problems: list[str] = []
    n = len(caption.caption_ko)
    if not MIN_LEN <= n <= MAX_LEN:
        problems.append(f"length {n}")
    if not re.search(r"[가-힣]", caption.caption_ko):
        problems.append("caption_ko not Korean")
    text = " ".join([caption.caption_ko, caption.caption_en, caption.setting])
    for word in forbidden:
        # 앞은 단어 경계, 뒤는 영문자만 막는다(한국어 이름 뒤에는 조사가 붙는다).
        if re.search(rf"(?<!\w){re.escape(word)}(?![a-z])", text, flags=re.IGNORECASE):
            problems.append(f"name/title: {word}")
    return problems


def movie_names(tmdb_id: int) -> list[str]:
    path = CREDITS_DIR / f"{tmdb_id}.json"
    if not path.exists():
        return []
    return credit_names(json.loads(path.read_text(encoding="utf-8")))


def load_rows(limit: int | None) -> list[SceneRow]:
    with SessionLocal() as session:
        movie_ids = select(Movie.id).order_by(Movie.id).limit(limit).scalar_subquery()
        stmt = (
            select(
                Scene.id,
                Movie.tmdb_id,
                Movie.title_ko,
                Movie.title_en,
                Scene.caption_ko,
                Scene.caption_en,
                Scene.tags,
                Scene.model_version,
            )
            .join(Movie, Scene.movie_id == Movie.id)
            .where(Movie.id.in_(movie_ids))
            .order_by(Scene.id)
        )
        return [SceneRow(*r) for r in session.execute(stmt).all()]


def windows_path(path: Path) -> str:
    """Windows 탐색기·엑셀에서 열 수 있는 WSL 경로."""
    distro = os.environ.get("WSL_DISTRO_NAME", "Ubuntu")
    return f"\\\\wsl.localhost\\{distro}" + str(path).replace("/", "\\")


def write_failures(rows: list[SceneRow]) -> None:
    with FAILURES_PATH.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["scene_id", "title_ko", "problems", "caption_ko", "image"])
        for r in rows:
            image = windows_path(scene_image_path(r.scene_id, r.tmdb_id))
            w.writerow([r.scene_id, r.title_ko, "; ".join(r.problems), r.caption_ko or "", image])


REVIEW_COLUMNS = [
    "no",
    "scene_id",
    "title_ko",
    "caption_ko",
    "setting",
    "time_of_day",
    "weather",
    "people",
    "actions",
    "objects",
    "colors",
    "text_in_frame",
    "hallucination",  # 검수자: 이미지에 없는 내용이 있으면 무엇인지 적는다
    "promo_image",  # 검수자: 영화 장면이 아니라 홍보용 포스터·합성 이미지면 O
    "note",
    "image",
]


def review_record(no: int, row: SceneRow, caption: SceneCaption) -> dict[str, Any]:
    return {
        "no": no,
        "scene_id": row.scene_id,
        "title_ko": row.title_ko,
        "caption_ko": caption.caption_ko,
        "setting": caption.setting,
        "time_of_day": caption.time_of_day,
        "weather": caption.weather or "",
        "people": caption.people.count,
        "actions": ", ".join(caption.people.actions),
        "objects": ", ".join(caption.objects),
        "colors": ", ".join(caption.colors),
        "text_in_frame": caption.text_in_frame or "",
        "hallucination": "",
        "promo_image": "",
        "note": "",
        "image": windows_path(scene_image_path(row.scene_id, row.tmdb_id)),
    }


def thumbnail_b64(path: Path, size: int = 480) -> str:
    with Image.open(path) as im:
        im.thumbnail((size, size))
        buf = io.BytesIO()
        im.convert("RGB").save(buf, "JPEG", quality=75)
    return base64.b64encode(buf.getvalue()).decode()


def write_review(sample: list[tuple[SceneRow, SceneCaption]]) -> None:
    records = [review_record(i, row, cap) for i, (row, cap) in enumerate(sample, 1)]
    with REVIEW_CSV_PATH.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=REVIEW_COLUMNS)
        w.writeheader()
        w.writerows(records)

    parts = [
        "<!doctype html><meta charset=utf-8><title>캡션 검수 50장</title><style>",
        "body{font-family:sans-serif;margin:16px;background:#fff;color:#111}",
        "table{border-collapse:collapse;width:100%}",
        "td{border:1px solid #ccc;padding:8px;vertical-align:top;font-size:14px}",
        ".m{color:#555;font-size:13px;margin-top:6px}</style>",
        "<h1>캡션 검수 50장</h1><p>caption_review.csv의 hallucination·promo_image 칸을 채운다.</p>",
        "<table>",
    ]
    for (row, _), rec in zip(sample, records, strict=True):
        img = thumbnail_b64(scene_image_path(row.scene_id, row.tmdb_id))
        meta = " · ".join(
            f"{k}: {html.escape(str(rec[k]))}"
            for k in ("setting", "time_of_day", "weather", "people", "actions", "objects")
        )
        parts.append(
            f"<tr><td>#{rec['no']} {html.escape(row.title_ko or '')}<br>"
            f"<img src='data:image/jpeg;base64,{img}'></td>"
            f"<td><b>{html.escape(rec['caption_ko'])}</b><div class=m>{meta}<br>"
            f"colors: {html.escape(rec['colors'])} · text: {html.escape(rec['text_in_frame'])}"
            f"<br>{html.escape(row.scene_id)}</div></td></tr>"
        )
    parts.append("</table>")
    REVIEW_HTML_PATH.write_text("".join(parts), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, help="movies 앞 N편의 장면만 (s01과 같은 순서)")
    parser.add_argument("--max-retries", type=int, default=2, help="실패 장면 재캡셔닝 횟수")
    parser.add_argument("--review-size", type=int, default=50)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--workers", type=int, default=3, help="동시 요청 수 (s04와 같은 이유로 3)")
    args = parser.parse_args()
    setup_logging()
    for noisy in ("httpx", "httpx2", "app.core.llm"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    settings = get_settings()
    backend = backend_config(settings)
    rows = load_rows(args.limit)
    titles = {r.tmdb_id: (r.title_ko, r.title_en) for r in rows}
    forbidden = {
        tmdb_id: forbidden_words(title_ko, title_en, movie_names(tmdb_id))
        for tmdb_id, (title_ko, title_en) in titles.items()
    }

    valid: dict[str, SceneCaption] = {}
    failing: list[SceneRow] = []
    for r in rows:
        cap = stored_caption(r)
        if isinstance(cap, str):
            r.problems = [cap]
        elif r.model_version != backend.model_version:
            r.problems = [f"model_version {r.model_version}"]
        else:
            r.problems = caption_problems(cap, forbidden[r.tmdb_id])
            if not r.problems:
                valid[r.scene_id] = cap
        if r.problems:
            failing.append(r)
    logger.info("s05: %d scenes, %d valid, %d need retry", len(rows), len(valid), len(failing))

    client = backend.make_client()
    state = State()
    try:
        for attempt in range(1, args.max_retries + 1):
            if not failing:
                break
            jobs = [SceneJob(r.scene_id, scene_image_path(r.scene_id, r.tmdb_id)) for r in failing]
            with ThreadPoolExecutor(max_workers=args.workers) as pool:
                results = list(
                    pool.map(
                        lambda j: caption_one(j, backend.model, client, backend.request_kwargs),
                        jobs,
                    )
                )
            still: list[SceneRow] = []
            for r, res in zip(failing, results, strict=True):
                if res.caption is None:
                    r.problems = [f"retry {attempt}: {res.error}"]
                    still.append(r)
                    continue
                problems = caption_problems(res.caption, forbidden[r.tmdb_id])
                if problems:
                    r.problems = [f"retry {attempt}: {p}" for p in problems]
                    still.append(r)
                    continue
                save_caption(r.scene_id, to_scene_values(res.caption, backend.model_version))
                state.mark_done(S04_STEP, r.scene_id, backend.model_version)
                valid[r.scene_id] = res.caption
            logger.info(
                "retry %d: %d fixed, %d still failing",
                attempt,
                len(failing) - len(still),
                len(still),
            )
            failing = still
    finally:
        state.close()

    REPORTS_DIR.mkdir(exist_ok=True)
    write_failures(failing)
    for r in failing:
        logger.warning("failed %s (%s): %s", r.scene_id, r.title_ko, "; ".join(r.problems)[:200])

    by_id = {r.scene_id: r for r in rows}
    sample_ids = random.Random(args.seed).sample(sorted(valid), min(args.review_size, len(valid)))
    write_review([(by_id[sid], valid[sid]) for sid in sample_ids])

    rate = len(failing) / max(len(rows), 1)
    logger.info(
        "s05 done: scenes=%d valid=%d failed=%d (%.2f%%, target < 2%%) -> %s, %s",
        len(rows),
        len(valid),
        len(failing),
        rate * 100,
        FAILURES_PATH.name,
        REVIEW_CSV_PATH.name,
    )


if __name__ == "__main__":
    main()
