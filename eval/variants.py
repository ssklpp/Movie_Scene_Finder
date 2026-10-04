"""실험용 색인 변형 (SPEC §11 E3 문서 언어, E4 토크나이저, E7 임베딩 차원).

운영 색인(s06~s08, 배포용 클라우드 Qdrant)은 건드리지 않고 **로컬 Qdrant**에
`exp_{언어}_{토크나이저}_{차원}_scenes`·`_movies` 컬렉션을 따로 만든다. 기준(ko, kiwi_dict, 1536)도
같은 방식으로 만들어 변형끼리 같은 조건으로 비교한다.

    uv run python -m eval.variants build --doc-lang en
    uv run python -m eval.variants build --tokenizer char2
    uv run python -m eval.variants build --dim 512

질의도 같은 변형으로 인코딩해야 하므로, 평가 설정에 `index:`가 있으면 run_eval이 `activate()`로
Qdrant 주소·컬렉션·임베딩 차원·토크나이저를 바꾼다(그 프로세스 안에서만).

- doc_lang: 검색 문서의 캡션만 바꾼다(ko / en / 둘 다). 장소·물건·장르·연대는 한국어 그대로.
  E3 결과로 운영 s06은 "둘 다"(both)가 됐다. 이 모듈의 ko는 이전 운영 문서와 같다.
- tokenizer: kiwi_dict(운영: Kiwi + 사용자 사전) / kiwi(사전 없음) / char2(어절별 문자 2-gram).
  문서와 질의 모두 같은 토크나이저를 쓰고, 줄거리(movies) 컬렉션에도 적용한다.
- embed_dim: text-embedding-3-small의 `dimensions` 값. 장면·줄거리 모두 적용한다.
"""

import argparse
import hashlib
import logging
import re
from collections.abc import Callable
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

import pyarrow as pa
import pyarrow.parquet as pq
from kiwipiepy import Kiwi
from pydantic import BaseModel
from qdrant_client import QdrantClient
from qdrant_client import models as qm
from sqlalchemy import select

from app.core import llm
from app.core.config import REPO_ROOT, get_settings
from app.core.logging import setup_logging
from app.db.models import Movie, Scene
from app.db.session import SessionLocal
from app.search import qdrant, sparse
from app.search.qdrant import PLOT_DENSE, PLOT_SPARSE, SCENE_DENSE, SCENE_SPARSE
from pipeline.s04_caption import backend_config
from pipeline.s06_build_docs import build_search_text
from pipeline.s07_embed import EMBED_BATCH, MOVIES_PARQUET, SCENES_PARQUET
from pipeline.s08_upload import create_collection, movie_payload, point_id, upsert_points

logger = logging.getLogger(__name__)

EXPERIMENT_QDRANT_URL = "http://localhost:6333"
DENSE_CACHE = REPO_ROOT / "pipeline" / "data" / "exp_dense_cache.parquet"
WORD = re.compile(r"\w+")

DocLang = Literal["ko", "en", "both"]
TokenizerKind = Literal["kiwi_dict", "kiwi", "char2"]


class IndexVariant(BaseModel):
    doc_lang: DocLang = "ko"
    tokenizer: TokenizerKind = "kiwi_dict"
    embed_dim: int = 1536

    @property
    def name(self) -> str:
        return f"exp_{self.doc_lang}_{self.tokenizer}_{self.embed_dim}"

    @property
    def scenes_collection(self) -> str:
        return f"{self.name}_scenes"

    @property
    def movies_collection(self) -> str:
        return f"{self.name}_movies"


# --- 토크나이저 ------------------------------------------------------------


@lru_cache
def plain_kiwi() -> Any:
    return Kiwi()


def char_bigrams(text: str) -> list[str]:
    """어절(\\w+)마다 문자 2-gram. 한 글자 어절은 그대로 둔다. 영어는 소문자."""
    tokens: list[str] = []
    for word in WORD.findall(text.lower()):
        tokens += [word] if len(word) == 1 else [word[i : i + 2] for i in range(len(word) - 1)]
    return tokens


# activate()가 sparse.tokenize를 바꿔 끼우므로 원래 함수를 따로 잡아 둔다.
_kiwi_tokenize = sparse.tokenize


def tokenizer_for(kind: TokenizerKind) -> Callable[[str], list[str]]:
    if kind == "kiwi_dict":
        return lambda text: _kiwi_tokenize(text, sparse.get_kiwi())
    if kind == "kiwi":
        return lambda text: _kiwi_tokenize(text, plain_kiwi())
    return char_bigrams


# --- 문서 ------------------------------------------------------------------


def scene_caption(lang: DocLang, caption_ko: str, caption_en: str | None) -> str:
    en = (caption_en or "").strip()
    if lang == "ko" or not en:
        return caption_ko
    return en if lang == "en" else f"{caption_ko}\n{en}"


def load_docs(lang: DocLang) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[int, Movie]]:
    """(장면 문서, 줄거리 문서, 영화). 장면은 s06과 같은 조건(현재 캡션 버전)만 쓴다."""
    model_version = backend_config(get_settings()).model_version
    with SessionLocal() as session:
        movies = {m.id: m for m in session.scalars(select(Movie))}
        scenes = list(session.scalars(select(Scene).order_by(Scene.movie_id, Scene.id)))
        session.expunge_all()
    scene_docs = [
        {
            "scene": s,
            "text": build_search_text(
                scene_caption(lang, s.caption_ko, s.caption_en),
                s.tags,
                movies[s.movie_id].genres,
                movies[s.movie_id].year,
            ),
        }
        for s in scenes
        if s.caption_ko and s.tags is not None and s.model_version == model_version
    ]
    plot_docs = [{"movie": m, "text": m.plot_ko} for m in movies.values() if m.plot_ko]
    return scene_docs, plot_docs, movies


# --- dense 캐시 ------------------------------------------------------------


def text_hash(text: str, model: str, dim: int) -> str:
    """s07과 같은 키라 운영 벡터(1536차원)를 그대로 재사용한다."""
    return hashlib.sha1(f"{model}|{dim}|{text}".encode()).hexdigest()


def load_cache() -> dict[str, list[float]]:
    cache: dict[str, list[float]] = {}
    for path in (SCENES_PARQUET, MOVIES_PARQUET, DENSE_CACHE):
        if path.exists():
            t = pq.read_table(path, columns=["text_hash", "dense"])
            cache.update(zip(t["text_hash"].to_pylist(), t["dense"].to_pylist(), strict=True))
    return cache


def save_cache(cache: dict[str, list[float]], path: Path = DENSE_CACHE) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    table = pa.table(
        {
            "text_hash": list(cache),
            "dense": pa.array(list(cache.values()), type=pa.list_(pa.float32())),
        }
    )
    pq.write_table(table, path)


def embed_texts(texts: list[str], dim: int, cache: dict[str, list[float]]) -> list[list[float]]:
    model = get_settings().embed_model
    hashes = [text_hash(t, model, dim) for t in texts]
    todo = [i for i, h in enumerate(hashes) if h not in cache]
    cost = 0.0
    for start in range(0, len(todo), EMBED_BATCH):
        chunk = todo[start : start + EMBED_BATCH]
        vectors, stats = llm.embed([texts[i] for i in chunk])  # 차원은 settings.embed_dim
        cost += stats.cost_usd
        for i, v in zip(chunk, vectors, strict=True):
            cache[hashes[i]] = v
    logger.info("dense: %d texts, %d embedded now ($%.4f)", len(texts), len(todo), cost)
    return [cache[h] for h in hashes]


# --- 적재 ------------------------------------------------------------------


def sparse_vectors(texts: list[str], tokenize: Callable[[str], list[str]]) -> list[qm.SparseVector]:
    token_lists = [tokenize(t) for t in texts]
    avgdl = sparse.average_doc_length(token_lists)
    out = []
    for tokens in token_lists:
        v = sparse.doc_vector(tokens, avgdl)
        out.append(qm.SparseVector(indices=v.indices, values=v.values))
    return out


def experiment_client() -> QdrantClient:
    return QdrantClient(url=EXPERIMENT_QDRANT_URL, timeout=int(get_settings().http_timeout_s))


def build(variant: IndexVariant, force: bool = False) -> None:
    client = experiment_client()
    names = {c.name for c in client.get_collections().collections}
    targets = (variant.scenes_collection, variant.movies_collection)
    if not force and all(n in names for n in targets):
        logger.info("%s: already built (use --force)", variant.name)
        return

    settings = get_settings()
    settings.embed_dim = variant.embed_dim
    tokenize = tokenizer_for(variant.tokenizer)
    scene_docs, plot_docs, movies = load_docs(variant.doc_lang)
    cache = load_cache()
    scene_dense = embed_texts([d["text"] for d in scene_docs], variant.embed_dim, cache)
    plot_dense = embed_texts([d["text"] for d in plot_docs], variant.embed_dim, cache)
    save_cache(cache)
    scene_sparse = sparse_vectors([d["text"] for d in scene_docs], tokenize)
    plot_sparse = sparse_vectors([d["text"] for d in plot_docs], tokenize)

    scene_points = [
        qm.PointStruct(
            id=point_id(d["scene"].id),
            vector={SCENE_DENSE: dense, SCENE_SPARSE: sv},
            payload={
                **movie_payload(movies[d["scene"].movie_id]),
                "scene_id": d["scene"].id,
                "source": d["scene"].source,
                "caption_ko": d["scene"].caption_ko,
                "model_version": d["scene"].model_version,
            },
        )
        for d, dense, sv in zip(scene_docs, scene_dense, scene_sparse, strict=True)
    ]
    plot_points = [
        qm.PointStruct(
            id=point_id(f"movie_{d['movie'].id}"),
            vector={PLOT_DENSE: dense, PLOT_SPARSE: sv},
            payload=movie_payload(d["movie"]),
        )
        for d, dense, sv in zip(plot_docs, plot_dense, plot_sparse, strict=True)
    ]
    for name, points, dense_name, sparse_name in (
        (variant.scenes_collection, scene_points, SCENE_DENSE, SCENE_SPARSE),
        (variant.movies_collection, plot_points, PLOT_DENSE, PLOT_SPARSE),
    ):
        if name in names:
            client.delete_collection(name)
        create_collection(client, name, dense_name, sparse_name, variant.embed_dim)
        upsert_points(client, name, points)
        logger.info("%s: %d points", name, len(points))


def activate(variant: IndexVariant) -> None:
    """이 프로세스의 질의가 변형 색인을 쓰게 한다(평가 전용)."""
    settings = get_settings()
    settings.qdrant_url = EXPERIMENT_QDRANT_URL
    settings.qdrant_api_key = ""
    settings.qdrant_scenes_alias = variant.scenes_collection
    settings.qdrant_movies_collection = variant.movies_collection
    settings.embed_dim = variant.embed_dim
    qdrant.get_qdrant.cache_clear()
    names = {c.name for c in qdrant.get_qdrant().get_collections().collections}
    missing = [n for n in (variant.scenes_collection, variant.movies_collection) if n not in names]
    if missing:
        raise SystemExit(f"{missing} not found: run `uv run python -m eval.variants build ...`")
    # hybrid.encode_query는 sparse.tokenize(text)를 부른다. 문서와 같은 토크나이저로 바꾼다.
    tokenize = tokenizer_for(variant.tokenizer)
    if variant.tokenizer != "kiwi_dict":
        sparse.tokenize = lambda text, kiwi=None: tokenize(text)  # type: ignore[assignment]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="변형 색인을 로컬 Qdrant에 만든다")
    b.add_argument("--doc-lang", choices=["ko", "en", "both"], default="ko")
    b.add_argument("--tokenizer", choices=["kiwi_dict", "kiwi", "char2"], default="kiwi_dict")
    b.add_argument("--dim", type=int, default=1536)
    b.add_argument("--force", action="store_true", help="이미 있어도 다시 만든다")
    args = parser.parse_args()
    setup_logging()
    for noisy in ("httpx", "httpx2", "app.core.llm"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    variant = IndexVariant(doc_lang=args.doc_lang, tokenizer=args.tokenizer, embed_dim=args.dim)
    build(variant, force=args.force)


if __name__ == "__main__":
    main()
