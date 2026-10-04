"""Qdrant 클라이언트와 컬렉션·벡터 이름 (SPEC §5.2). 적재(s08)와 검색이 같은 이름을 쓴다."""

from functools import lru_cache

from qdrant_client import QdrantClient

from app.core.config import get_settings

SCENES_COLLECTION_PREFIX = "scenes_v"  # 실제 컬렉션은 scenes_v{n}, 검색은 별칭(QDRANT_SCENES_ALIAS)
MOVIES_COLLECTION = "movies"

SCENE_DENSE = "dense"
SCENE_SPARSE = "sparse_ko"
PLOT_DENSE = "plot_dense"
PLOT_SPARSE = "plot_sparse_ko"


@lru_cache
def get_qdrant() -> QdrantClient:
    s = get_settings()
    return QdrantClient(
        url=s.qdrant_url, api_key=s.qdrant_api_key or None, timeout=int(s.http_timeout_s)
    )


def decade_key(year: int | None) -> str | None:
    """payload·필터용 연대 값. 2019 → "2010s" (재질문 선택지 형식과 같다)."""
    return f"{year // 10 * 10}s" if year else None
