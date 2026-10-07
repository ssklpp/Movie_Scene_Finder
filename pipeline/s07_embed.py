"""s07: 장면 검색 문서와 영화 줄거리를 dense·sparse 벡터로 바꿔 parquet에 쓴다 (SPEC §6, §7.2).

- dense: EMBED_MODEL(EMBED_DIM), 100개씩 배치. `core/llm.embed`를 거친다.
  문서 내용 해시(모델·차원 포함)로 기존 parquet의 벡터를 재사용하므로, 다시 실행하면 바뀐 문서만
  새로 임베딩한다.
- sparse: `app.search.sparse`(backend 질의와 같은 함수)의 BM25 문서 가중치. avgdl은 컬렉션별로
  계산해 `pipeline/data/bm25_stats.json`에 쓴다. 가벼우므로 매번 다시 계산한다.

- 영화 문서 = 줄거리(plot_ko) + 다음 줄에 KMDb 키워드(keywords_ko, 쉼표 구분). 키워드는
  KW 실험(human 검색만 R@5 0.16 → 0.20) 결과로 넣었다.

입력: pipeline/data/search_docs.jsonl(s06), movies.plot_ko·keywords_ko
출력: pipeline/data/vectors/scenes.parquet, movies.parquet
"""

import argparse
import hashlib
import json
import logging
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
from sqlalchemy import select

from app.core import llm
from app.core.config import REPO_ROOT, get_settings
from app.core.logging import setup_logging
from app.db.models import Movie
from app.db.session import SessionLocal
from app.search import sparse
from pipeline.s06_build_docs import SEARCH_DOCS_PATH

logger = logging.getLogger(__name__)

VECTORS_DIR = REPO_ROOT / "pipeline" / "data" / "vectors"
SCENES_PARQUET = VECTORS_DIR / "scenes.parquet"
MOVIES_PARQUET = VECTORS_DIR / "movies.parquet"
EMBED_BATCH = 100


def text_hash(text: str, model: str, dim: int) -> str:
    return hashlib.sha1(f"{model}|{dim}|{text}".encode()).hexdigest()


def movie_doc(plot_ko: str | None, keywords_ko: Sequence[str] | None) -> str:
    """영화 검색 문서. 줄거리 다음 줄에 키워드를 쉼표로 잇는다. 둘 다 없으면 빈 문자열."""
    parts = [plot_ko or "", ", ".join(keywords_ko or [])]
    return "\n".join(p for p in parts if p)


def load_dense_cache(path: Path) -> dict[str, list[float]]:
    if not path.exists():
        return {}
    table = pq.read_table(path, columns=["text_hash", "dense"])
    return dict(zip(table["text_hash"].to_pylist(), table["dense"].to_pylist(), strict=True))


def embed_with_cache(
    texts: Sequence[str], hashes: Sequence[str], cache: dict[str, list[float]], batch: int
) -> tuple[list[list[float]], int, float]:
    """(벡터, 새로 임베딩한 수, 비용 USD). 캐시에 없는 문서만 batch개씩 임베딩한다."""
    todo = [i for i, h in enumerate(hashes) if h not in cache]
    cost = 0.0
    for start in range(0, len(todo), batch):
        chunk = todo[start : start + batch]
        vectors, stats = llm.embed([texts[i] for i in chunk])
        cost += stats.cost_usd
        for i, v in zip(chunk, vectors, strict=True):
            cache[hashes[i]] = v
        logger.info("embedded %d/%d", min(start + batch, len(todo)), len(todo))
    return [cache[h] for h in hashes], len(todo), cost


def sparse_columns(
    token_lists: Sequence[Sequence[str]], avgdl: float
) -> tuple[list[list[int]], list[list[float]]]:
    vectors = [sparse.doc_vector(tokens, avgdl) for tokens in token_lists]
    return [v.indices for v in vectors], [v.values for v in vectors]


def write_parquet(path: Path, columns: dict[str, Any], dim: int) -> None:
    schema_fields = {
        "dense": pa.list_(pa.float32(), dim),
        "sparse_indices": pa.list_(pa.uint32()),
        "sparse_values": pa.list_(pa.float32()),
    }
    arrays = {
        name: pa.array(values, type=schema_fields.get(name)) for name, values in columns.items()
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".part")
    pq.write_table(pa.table(arrays), tmp)
    tmp.replace(path)


def selected_movie_ids(limit: int | None) -> set[int]:
    with SessionLocal() as session:
        return set(session.scalars(select(Movie.id).order_by(Movie.id).limit(limit)))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, help="movies 앞 N편만 (s01과 같은 순서)")
    parser.add_argument("--force", action="store_true", help="dense 캐시를 무시하고 다시 임베딩")
    args = parser.parse_args()
    setup_logging()
    for noisy in ("httpx", "httpx2", "app.core.llm"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    settings = get_settings()
    model, dim = settings.embed_model, settings.embed_dim
    movie_ids = selected_movie_ids(args.limit)

    docs = [json.loads(line) for line in SEARCH_DOCS_PATH.open(encoding="utf-8")]
    docs = [d for d in docs if d["movie_id"] in movie_ids]
    with SessionLocal() as session:
        stmt = (
            select(Movie.id, Movie.tmdb_id, Movie.plot_ko, Movie.keywords_ko)
            .where(Movie.id.in_(movie_ids))
            .order_by(Movie.id)
        )
        movies = [
            (mid, tid, text)
            for mid, tid, plot, kw in session.execute(stmt).all()
            if (text := movie_doc(plot, kw))
        ]
    logger.info(
        "s07: %d scene docs, %d movie docs (model=%s dim=%d)", len(docs), len(movies), model, dim
    )

    kiwi = sparse.get_kiwi()
    scene_texts: list[str] = [d["search_text"] for d in docs]
    plot_texts: list[str] = [plot for _, _, plot in movies]
    scene_tokens = [sparse.tokenize(t, kiwi) for t in scene_texts]
    plot_tokens = [sparse.tokenize(t, kiwi) for t in plot_texts]
    stats = {
        "scenes": {"avgdl": sparse.average_doc_length(scene_tokens), "n_docs": len(docs)},
        "movies": {"avgdl": sparse.average_doc_length(plot_tokens), "n_docs": len(movies)},
    }
    sparse.save_bm25_stats(stats)
    logger.info("bm25 stats: %s", stats)

    total_cost = 0.0
    for path, texts, token_lists, avgdl, id_columns in (
        (
            SCENES_PARQUET,
            scene_texts,
            scene_tokens,
            stats["scenes"]["avgdl"],
            {
                "scene_id": [d["scene_id"] for d in docs],
                "movie_id": [d["movie_id"] for d in docs],
                "tmdb_id": [d["tmdb_id"] for d in docs],
                "model_version": [d["model_version"] for d in docs],
            },
        ),
        (
            MOVIES_PARQUET,
            plot_texts,
            plot_tokens,
            stats["movies"]["avgdl"],
            {"movie_id": [m for m, _, _ in movies], "tmdb_id": [t for _, t, _ in movies]},
        ),
    ):
        hashes = [text_hash(t, model, dim) for t in texts]
        cache = {} if args.force else load_dense_cache(path)
        dense, new, cost = embed_with_cache(texts, hashes, cache, EMBED_BATCH)
        total_cost += cost
        indices, values = sparse_columns(token_lists, avgdl)
        write_parquet(
            path,
            {
                **id_columns,
                "text_hash": hashes,
                "dense": dense,
                "sparse_indices": indices,
                "sparse_values": values,
            },
            dim,
        )
        logger.info(
            "%s: %d rows, %d newly embedded, cost_usd=%.4f", path.name, len(texts), new, cost
        )
    logger.info("s07 done: cost_usd=%.4f", total_cost)


if __name__ == "__main__":
    main()
