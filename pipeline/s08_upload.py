"""s08: s07 벡터를 Qdrant에 적재한다 (SPEC §5.2, §6).

- scenes: 새 컬렉션 scenes_v{n} 생성 → 256개씩 upsert → 포인트 수 확인 → 별칭
  (QDRANT_SCENES_ALIAS, 기본 "scenes")을 한 번에 옮긴다. 이전 버전은 되돌리기용으로
  `--keep`개만 남기고 지운다.
- movies: 이름이 고정이라 매번 새로 만든다.
- 포인트 ID는 Qdrant가 정수·UUID만 받으므로 scene_id(또는 movie id)에서 만든 UUID5다.
  원래 scene_id는 payload에 둔다.
- 입력 parquet가 그대로면 건너뛴다(state.sqlite). `QDRANT_URL`만 바꾸면 클라우드에도 적재된다.
- 썸네일 R2 업로드(SPEC)는 R2 설정이 생기는 Phase 5에서 추가한다.
"""

import argparse
import hashlib
import logging
import re
import uuid
from collections.abc import Iterator, Sequence
from functools import partial
from typing import Any

import pyarrow.parquet as pq
from qdrant_client import QdrantClient
from qdrant_client import models as qm
from sqlalchemy import func, select

from app.core.config import get_settings
from app.core.logging import setup_logging
from app.db.models import Movie, Scene
from app.db.session import SessionLocal
from app.search.qdrant import (
    MOVIES_COLLECTION,
    PLOT_DENSE,
    PLOT_SPARSE,
    SCENE_DENSE,
    SCENE_SPARSE,
    SCENES_COLLECTION_PREFIX,
    decade_key,
    get_qdrant,
)
from pipeline.common.retry import retry
from pipeline.common.state import State
from pipeline.s07_embed import MOVIES_PARQUET, SCENES_PARQUET

logger = logging.getLogger(__name__)

STEP = "s08"
UPSERT_BATCH = 256
POINT_NAMESPACE = uuid.UUID("6f1c2b0e-3a4d-4e7b-9c1a-5d2e8f0b7a11")
# 필터에 쓰는 payload 필드 (SPEC §5.2의 * 표시)
PAYLOAD_INDEXES: dict[str, qm.PayloadSchemaType] = {
    "movie_id": qm.PayloadSchemaType.INTEGER,
    "year": qm.PayloadSchemaType.INTEGER,
    "decade": qm.PayloadSchemaType.KEYWORD,
    "country": qm.PayloadSchemaType.KEYWORD,
    "genres": qm.PayloadSchemaType.KEYWORD,
    "is_animation": qm.PayloadSchemaType.BOOL,
}


def point_id(key: str) -> str:
    return str(uuid.uuid5(POINT_NAMESPACE, key))


def next_version(collection_names: Sequence[str], prefix: str = SCENES_COLLECTION_PREFIX) -> int:
    versions = [
        int(m.group(1)) for n in collection_names if (m := re.fullmatch(rf"{prefix}(\d+)", n))
    ]
    return max(versions, default=0) + 1


def stale_versions(
    collection_names: Sequence[str], keep: int, prefix: str = SCENES_COLLECTION_PREFIX
) -> list[str]:
    """최신 keep개를 뺀 나머지 scenes_v{n} 컬렉션."""
    versioned = sorted(
        (int(m.group(1)), n) for n in collection_names if (m := re.fullmatch(rf"{prefix}(\d+)", n))
    )
    return [n for _, n in versioned[: max(len(versioned) - keep, 0)]]


def batches[T](items: Sequence[T], size: int) -> Iterator[Sequence[T]]:
    for start in range(0, len(items), size):
        yield items[start : start + size]


def movie_payload(movie: Movie) -> dict[str, Any]:
    return {
        "movie_id": movie.id,
        "tmdb_id": movie.tmdb_id,
        "year": movie.year,
        "decade": decade_key(movie.year),
        "country": movie.country,
        "genres": movie.genres or [],
        "is_animation": bool(movie.is_animation),
    }


def fingerprint(*paths: Any) -> str:
    h = hashlib.sha1()
    for path in paths:
        h.update(path.read_bytes())
    return h.hexdigest()


def create_collection(
    client: QdrantClient, name: str, dense_name: str, sparse_name: str, dim: int
) -> None:
    retry(
        lambda: client.create_collection(
            collection_name=name,
            vectors_config={dense_name: qm.VectorParams(size=dim, distance=qm.Distance.COSINE)},
            sparse_vectors_config={sparse_name: qm.SparseVectorParams(modifier=qm.Modifier.IDF)},
        ),
        f"create {name}",
    )
    for field, schema in PAYLOAD_INDEXES.items():
        retry(
            partial(
                client.create_payload_index,
                collection_name=name,
                field_name=field,
                field_schema=schema,
            ),
            f"index {name}.{field}",
        )


def upsert_points(client: QdrantClient, name: str, points: Sequence[qm.PointStruct]) -> None:
    for i, chunk in enumerate(batches(points, UPSERT_BATCH), 1):
        retry(
            partial(client.upsert, collection_name=name, points=list(chunk), wait=True),
            f"upsert {name} batch {i}",
        )
    count = client.count(collection_name=name, exact=True).count
    if count != len(points):
        raise RuntimeError(f"{name}: {count} points after upsert, expected {len(points)}")


def scene_points(
    movies: dict[int, Movie], scenes: dict[str, Scene], limit_ids: set[int]
) -> list[qm.PointStruct]:
    table = pq.read_table(SCENES_PARQUET).to_pylist()
    points = []
    for row in table:
        if row["movie_id"] not in limit_ids:
            continue
        scene = scenes[row["scene_id"]]
        points.append(
            qm.PointStruct(
                id=point_id(row["scene_id"]),
                vector={
                    SCENE_DENSE: row["dense"],
                    SCENE_SPARSE: qm.SparseVector(
                        indices=row["sparse_indices"], values=row["sparse_values"]
                    ),
                },
                payload={
                    **movie_payload(movies[row["movie_id"]]),
                    "scene_id": row["scene_id"],
                    "source": scene.source,
                    "caption_ko": scene.caption_ko,
                    "model_version": scene.model_version,
                },
            )
        )
    return points


def movie_points(movies: dict[int, Movie], limit_ids: set[int]) -> list[qm.PointStruct]:
    table = pq.read_table(MOVIES_PARQUET).to_pylist()
    return [
        qm.PointStruct(
            id=point_id(f"movie_{row['movie_id']}"),
            vector={
                PLOT_DENSE: row["dense"],
                PLOT_SPARSE: qm.SparseVector(
                    indices=row["sparse_indices"], values=row["sparse_values"]
                ),
            },
            payload=movie_payload(movies[row["movie_id"]]),
        )
        for row in table
        if row["movie_id"] in limit_ids
    ]


def swap_alias(client: QdrantClient, alias: str, collection: str) -> None:
    current = {a.alias_name for a in client.get_aliases().aliases}
    ops: list[qm.CreateAliasOperation | qm.DeleteAliasOperation] = []
    if alias in current:
        ops.append(qm.DeleteAliasOperation(delete_alias=qm.DeleteAlias(alias_name=alias)))
    ops.append(
        qm.CreateAliasOperation(
            create_alias=qm.CreateAlias(collection_name=collection, alias_name=alias)
        )
    )
    retry(lambda: client.update_collection_aliases(change_aliases_operations=ops), "swap alias")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, help="movies 앞 N편만 (s01과 같은 순서)")
    parser.add_argument("--force", action="store_true", help="입력이 같아도 다시 적재")
    parser.add_argument("--keep", type=int, default=2, help="남길 scenes_v{n} 개수(현재 포함)")
    args = parser.parse_args()
    setup_logging()
    logging.getLogger("httpx").setLevel(logging.WARNING)

    settings = get_settings()
    alias, dim = settings.qdrant_scenes_alias, settings.embed_dim
    client = get_qdrant()
    state = State()
    key = f"{fingerprint(SCENES_PARQUET, MOVIES_PARQUET)}:limit={args.limit}"
    aliases = {a.alias_name for a in client.get_aliases().aliases}
    if not args.force and alias in aliases and state.is_done(STEP, key):
        logger.info("s08: vectors unchanged since last upload; skipping (use --force)")
        state.close()
        return

    with SessionLocal() as session:
        limit_ids = set(session.scalars(select(Movie.id).order_by(Movie.id).limit(args.limit)))
        movies = {m.id: m for m in session.scalars(select(Movie))}
        scenes = {s.id: s for s in session.scalars(select(Scene))}
        session.expunge_all()

    names = [c.name for c in client.get_collections().collections]
    collection = f"{SCENES_COLLECTION_PREFIX}{next_version(names)}"
    points = scene_points(movies, scenes, limit_ids)
    logger.info("s08: creating %s with %d scene points", collection, len(points))
    create_collection(client, collection, SCENE_DENSE, SCENE_SPARSE, dim)
    upsert_points(client, collection, points)
    swap_alias(client, alias, collection)
    logger.info("alias %s -> %s", alias, collection)

    plots = movie_points(movies, limit_ids)
    if MOVIES_COLLECTION in names:
        retry(lambda: client.delete_collection(MOVIES_COLLECTION), "delete movies")
    create_collection(client, MOVIES_COLLECTION, PLOT_DENSE, PLOT_SPARSE, dim)
    upsert_points(client, MOVIES_COLLECTION, plots)
    logger.info("%s: %d movie points", MOVIES_COLLECTION, len(plots))

    names = [c.name for c in client.get_collections().collections]
    for old in stale_versions(names, args.keep):
        retry(partial(client.delete_collection, old), f"delete {old}")
        logger.info("deleted old collection %s", old)

    state.mark_done(STEP, key)
    state.close()

    with SessionLocal() as session:
        stmt = select(func.count()).select_from(Scene).where(Scene.movie_id.in_(limit_ids))
        db_scenes = session.scalar(stmt) or 0
    qdrant_scenes = client.count(collection_name=alias, exact=True).count
    status = "OK" if qdrant_scenes == db_scenes else "MISMATCH"
    logger.info(
        "s08 done: %s alias %s points=%d, scenes rows=%d (%s)",
        alias,
        collection,
        qdrant_scenes,
        db_scenes,
        status,
    )
    logger.info("thumbnail upload to R2 skipped (added in Phase 5)")


if __name__ == "__main__":
    main()
