"""하이브리드 검색 (SPEC §7.3).

질의를 한 번 임베딩한 뒤 Qdrant Query API로
- 장면: prefetch [dense limit 50, sparse_ko limit 50] → RRF → SCENE_TOPK
- 영화 줄거리: 같은 방식으로 상위 20편
을 찾는다. hard_filters는 모든 prefetch에 payload 필터로 건다.

mode는 E1 실험용이다: "hybrid"(기본), "dense"·"sparse"(prefetch 하나만, 점수는 같은 RRF).
Qdrant RRF 점수는 1 / (1 + 순위)다(1위 0.5, 2위 0.333 ...).
"""

from collections.abc import Mapping
from dataclasses import dataclass
from functools import partial
from typing import Literal

from pydantic import BaseModel
from qdrant_client import QdrantClient
from qdrant_client import models as qm

from app.core import llm
from app.core.config import get_settings
from app.core.retry import retry
from app.search import sparse
from app.search.filters import MovieAttrs, to_qdrant_filter
from app.search.qdrant import (
    PLOT_DENSE,
    PLOT_SPARSE,
    SCENE_DENSE,
    SCENE_SPARSE,
    get_qdrant,
)

Mode = Literal["hybrid", "dense", "sparse"]
PREFETCH_LIMIT = 50
PLOT_TOPK = 20


class SceneHit(BaseModel):
    scene_id: str
    movie_id: int
    score: float
    caption_ko: str
    attrs: MovieAttrs


class PlotHit(BaseModel):
    movie_id: int
    score: float
    attrs: MovieAttrs


@dataclass(frozen=True)
class QueryVectors:
    dense: list[float]
    sparse: sparse.SparseVector


@dataclass(frozen=True)
class RetrievalResult:
    scene_hits: list[SceneHit]
    plot_hits: list[PlotHit]
    embed_stats: llm.CallStats | None


def encode_query(text: str) -> tuple[QueryVectors, llm.CallStats]:
    dense, stats = llm.embed([text])
    return QueryVectors(dense[0], sparse.query_vector(sparse.tokenize(text))), stats


def build_prefetch(
    vectors: QueryVectors,
    dense_name: str,
    sparse_name: str,
    mode: Mode,
    query_filter: qm.Filter | None,
) -> list[qm.Prefetch]:
    prefetch: list[qm.Prefetch] = []
    if mode in ("hybrid", "dense"):
        prefetch.append(
            qm.Prefetch(
                query=vectors.dense, using=dense_name, limit=PREFETCH_LIMIT, filter=query_filter
            )
        )
    if mode in ("hybrid", "sparse") and vectors.sparse.indices:
        prefetch.append(
            qm.Prefetch(
                query=qm.SparseVector(indices=vectors.sparse.indices, values=vectors.sparse.values),
                using=sparse_name,
                limit=PREFETCH_LIMIT,
                filter=query_filter,
            )
        )
    return prefetch


def _fused_query(
    client: QdrantClient, collection: str, prefetch: list[qm.Prefetch], limit: int
) -> list[qm.ScoredPoint]:
    if not prefetch:  # sparse 모드인데 질의에 남는 토큰이 없을 때
        return []
    response = retry(
        partial(
            client.query_points,
            collection_name=collection,
            prefetch=prefetch,
            query=qm.FusionQuery(fusion=qm.Fusion.RRF),
            limit=limit,
            with_payload=True,
        ),
        f"query {collection}",
    )
    return list(response.points)


def search_scenes(
    vectors: QueryVectors,
    mode: Mode = "hybrid",
    hard_filters: Mapping[str, str] | None = None,
    limit: int | None = None,
    client: QdrantClient | None = None,
) -> list[SceneHit]:
    s = get_settings()
    prefetch = build_prefetch(
        vectors, SCENE_DENSE, SCENE_SPARSE, mode, to_qdrant_filter(hard_filters)
    )
    points = _fused_query(
        client or get_qdrant(), s.qdrant_scenes_alias, prefetch, limit or s.scene_topk
    )
    return [
        SceneHit(
            scene_id=p.payload["scene_id"],
            movie_id=p.payload["movie_id"],
            score=p.score,
            caption_ko=p.payload.get("caption_ko") or "",
            attrs=MovieAttrs.from_payload(p.payload),
        )
        for p in points
        if p.payload
    ]


def search_plots(
    vectors: QueryVectors,
    mode: Mode = "hybrid",
    hard_filters: Mapping[str, str] | None = None,
    limit: int = PLOT_TOPK,
    client: QdrantClient | None = None,
) -> list[PlotHit]:
    prefetch = build_prefetch(
        vectors, PLOT_DENSE, PLOT_SPARSE, mode, to_qdrant_filter(hard_filters)
    )
    collection = get_settings().qdrant_movies_collection
    points = _fused_query(client or get_qdrant(), collection, prefetch, limit)
    return [
        PlotHit(
            movie_id=p.payload["movie_id"],
            score=p.score,
            attrs=MovieAttrs.from_payload(p.payload),
        )
        for p in points
        if p.payload
    ]


def retrieve(
    text: str,
    mode: Mode = "hybrid",
    hard_filters: Mapping[str, str] | None = None,
    client: QdrantClient | None = None,
) -> RetrievalResult:
    """장면과 줄거리를 함께 검색한다. 질의 임베딩은 한 번만 한다."""
    vectors, stats = encode_query(text)
    return RetrievalResult(
        scene_hits=search_scenes(vectors, mode, hard_filters, client=client),
        plot_hits=search_plots(vectors, mode, hard_filters, client=client),
        embed_stats=stats,
    )
