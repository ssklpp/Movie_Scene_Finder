"""synthetic 평가 질의 (SPEC §11): 장면 캡션을 LLM_MODEL_STRONG이 "흐릿한 기억" 문체로 다시 쓴다.

- 영화마다 장면 하나를 무작위로 고른다(300편 → 300개). 고정 시드로 dev 200 / test 100.
- 원문 단어의 50% 이상을 바꾸고 세부 하나를 일부러 틀리게 한다. 바뀌었는지는 Kiwi 토큰
  (`search/sparse.tokenize`) 겹침 비율로 확인하고, 50%를 넘게 겹치면 최대 2회 다시 만든다.
- 영화 제목·인물 이름은 쓰지 않는다.
- 이미 만든 질의(같은 id)는 건너뛰므로 중단 후 다시 실행하면 이어서 만든다.

    uv run python -m eval.make_synthetic [--limit N]
"""

import argparse
import json
import logging
import random
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from openai.types.chat import ChatCompletionMessageParam
from pydantic import BaseModel
from sqlalchemy import select

from app.core import llm
from app.core.config import REPO_ROOT, get_settings
from app.core.logging import setup_logging
from app.db.models import Movie, Scene
from app.db.session import SessionLocal
from app.search import sparse

logger = logging.getLogger(__name__)

VERSION = "v1"
OUT_PATH = REPO_ROOT / "eval" / "datasets" / f"synthetic_{VERSION}.jsonl"
DEV_SIZE = 200
MAX_OVERLAP = 0.5
MAX_ATTEMPTS = 3  # 첫 시도 + 재시도 2회

SYSTEM_PROMPT = """너는 영화를 본 지 오래된 사람이다.
장면 설명을 받으면, 그 장면을 흐릿하게 기억하는 사람이 검색창에 칠 법한 문장으로 다시 쓴다.

규칙:
- 한국어 구어체 한두 문장, 20~80자. "~였던 것 같은데", "~나오는 영화" 같은 말투.
- 원문의 단어를 절반 이상 다른 말로 바꾼다. 같은 뜻의 다른 표현, 더 뭉뚱그린 표현을 쓴다.
- 세부 하나를 일부러 틀리게 기억한다(색, 수, 시간대, 날씨, 물건 중 하나). 무엇을 어떻게
  바꿨는지 distorted_detail에 적는다.
- 영화 제목, 배우·등장인물 이름은 쓰지 않는다. 원문에 없는 내용은 지어내지 않는다."""


class SyntheticQuery(BaseModel):
    query: str
    distorted_detail: str


@dataclass(frozen=True)
class Source:
    id: str
    scene_id: str
    movie_id: int
    tmdb_id: int
    caption_ko: str
    split: str


def token_overlap(source: str, rewritten: str) -> float:
    """원문 토큰 중 다시 쓴 문장에도 남아 있는 비율. 0이면 모두 바뀜."""
    src = set(sparse.tokenize(source))
    if not src:
        return 0.0
    return len(src & set(sparse.tokenize(rewritten))) / len(src)


def pick_sources(rows: list[tuple[str, int, int, str]], seed: int, dev_size: int) -> list[Source]:
    """(scene_id, movie_id, tmdb_id, caption_ko) 중 영화마다 하나를 고르고 dev/test로 나눈다."""
    rng = random.Random(seed)
    by_movie: dict[int, list[tuple[str, int, int, str]]] = {}
    for row in sorted(rows):
        by_movie.setdefault(row[1], []).append(row)
    picked = [rng.choice(by_movie[m]) for m in sorted(by_movie)]
    rng.shuffle(picked)
    return [
        Source(
            id=f"syn-{i:04d}",
            scene_id=scene_id,
            movie_id=movie_id,
            tmdb_id=tmdb_id,
            caption_ko=caption,
            split="dev" if i <= dev_size else "test",
        )
        for i, (scene_id, movie_id, tmdb_id, caption) in enumerate(picked, start=1)
    ]


def build_messages(caption_ko: str) -> list[ChatCompletionMessageParam]:
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"장면 설명: {caption_ko}"},
    ]


def to_record(src: Source, gen: SyntheticQuery, overlap: float) -> dict[str, Any]:
    return {
        "id": src.id,
        "query": gen.query,
        "image_path": None,
        "answer_movie_id": src.movie_id,
        "answer_tmdb_id": src.tmdb_id,
        "source": "synthetic",
        "split": src.split,
        "version": VERSION,
        "scene_id": src.scene_id,
        "distorted_detail": gen.distorted_detail,
        "overlap": round(overlap, 3),
    }


def generate(src: Source, model: str) -> tuple[dict[str, Any] | None, float]:
    """(레코드, 비용). 겹침이 MAX_OVERLAP 이하가 될 때까지 최대 MAX_ATTEMPTS번 만든다."""
    cost = 0.0
    best: tuple[SyntheticQuery, float] | None = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            gen, stats = llm.parse(
                build_messages(src.caption_ko),
                SyntheticQuery,
                model=model,
                reasoning_effort="low",
                max_completion_tokens=1500,
            )
        except Exception as e:
            logger.warning("%s attempt %d failed: %s", src.id, attempt, str(e)[:200])
            continue
        cost += stats.cost_usd
        if gen is None:
            continue
        overlap = token_overlap(src.caption_ko, gen.query)
        if best is None or overlap < best[1]:
            best = (gen, overlap)
        if overlap <= MAX_OVERLAP:
            break
    if best is None:
        return None, cost
    if best[1] > MAX_OVERLAP:
        logger.warning("%s: overlap %.2f > %.2f after retries", src.id, best[1], MAX_OVERLAP)
    return to_record(src, *best), cost


def load_existing(path: Path) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}
    return {r["id"]: r for r in map(json.loads, path.read_text(encoding="utf-8").splitlines())}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, help="앞 N개 질의만 만든다(시험용)")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--workers", type=int, default=3)
    args = parser.parse_args()
    setup_logging()
    for noisy in ("httpx", "httpx2", "app.core.llm"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    model = get_settings().llm_model_strong
    with SessionLocal() as session:
        stmt = (
            select(Scene.id, Scene.movie_id, Movie.tmdb_id, Scene.caption_ko)
            .join(Movie, Scene.movie_id == Movie.id)
            .where(Scene.caption_ko.is_not(None))
        )
        rows = [(sid, mid, tid, cap) for sid, mid, tid, cap in session.execute(stmt).all() if cap]
    sources = pick_sources(rows, args.seed, DEV_SIZE)[: args.limit]
    existing = load_existing(OUT_PATH)
    todo = [s for s in sources if s.id not in existing]
    logger.info(
        "synthetic: %d sources, %d existing, %d to generate (model=%s)",
        len(sources),
        len(existing),
        len(todo),
        model,
    )

    sparse.get_kiwi()  # 스레드에서 쓰기 전에 사전을 한 번 읽는다
    total_cost = 0.0
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        for src, (record, cost) in zip(
            todo, pool.map(lambda s: generate(s, model), todo), strict=True
        ):
            total_cost += cost
            if record is None:
                logger.warning("%s: no query generated", src.id)
                continue
            existing[src.id] = record

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    ordered = [existing[k] for k in sorted(existing)]
    OUT_PATH.write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in ordered), encoding="utf-8"
    )
    over = sum(1 for r in ordered if r["overlap"] > MAX_OVERLAP)
    splits = {s: sum(1 for r in ordered if r["split"] == s) for s in ("dev", "test")}
    logger.info(
        "synthetic done: %d records %s, overlap>%.1f: %d, cost_usd=%.4f -> %s",
        len(ordered),
        splits,
        MAX_OVERLAP,
        over,
        total_cost,
        OUT_PATH,
    )


if __name__ == "__main__":
    main()
