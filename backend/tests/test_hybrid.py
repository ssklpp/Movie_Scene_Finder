from types import SimpleNamespace
from typing import Any, cast

import pytest
from qdrant_client import QdrantClient
from qdrant_client import models as qm

from app.core.llm import CallStats
from app.search import hybrid
from app.search.qdrant import MOVIES_COLLECTION
from app.search.sparse import SparseVector

VECTORS = hybrid.QueryVectors(dense=[0.1, 0.2], sparse=SparseVector([7, 9], [1.0, 1.0]))


class FakeQdrant:
    def __init__(self, points: list[qm.ScoredPoint]) -> None:
        self.points = points
        self.calls: list[dict[str, Any]] = []

    def query_points(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        return SimpleNamespace(points=self.points)


def _point(score: float, **payload: Any) -> qm.ScoredPoint:
    return qm.ScoredPoint(id=1, version=0, score=score, payload=payload)


@pytest.mark.parametrize(
    ("mode", "usings"),
    [("hybrid", ["dense", "sparse_ko"]), ("dense", ["dense"]), ("sparse", ["sparse_ko"])],
)
def test_build_prefetch_modes(mode: hybrid.Mode, usings: list[str]) -> None:
    prefetch = hybrid.build_prefetch(VECTORS, "dense", "sparse_ko", mode, None)
    assert [p.using for p in prefetch] == usings
    assert all(p.limit == 50 for p in prefetch)


def test_hard_filter_applied_to_every_prefetch() -> None:
    flt = qm.Filter(must=[qm.FieldCondition(key="decade", match=qm.MatchValue(value="2010s"))])
    prefetch = hybrid.build_prefetch(VECTORS, "dense", "sparse_ko", "hybrid", flt)
    assert len(prefetch) == 2 and all(p.filter == flt for p in prefetch)


def test_empty_sparse_query_skips_sparse_prefetch() -> None:
    vectors = hybrid.QueryVectors(dense=[0.1], sparse=SparseVector([], []))
    assert [p.using for p in hybrid.build_prefetch(vectors, "d", "s", "hybrid", None)] == ["d"]
    assert hybrid.build_prefetch(vectors, "d", "s", "sparse", None) == []


def test_search_scenes_query_and_mapping() -> None:
    fake = FakeQdrant(
        [
            _point(
                0.5,
                scene_id="496243_backdrop_0",
                movie_id=13,
                caption_ko="가족이 피자 상자를 접는다.",
                decade="2010s",
                country="KR",
                genres=["드라마"],
                is_animation=False,
                year=2019,
            )
        ]
    )
    hits = hybrid.search_scenes(
        VECTORS, hard_filters={"country": "KR"}, limit=7, client=cast(QdrantClient, fake)
    )
    call = fake.calls[0]
    assert call["collection_name"] == "scenes" and call["limit"] == 7
    assert call["query"] == qm.FusionQuery(fusion=qm.Fusion.RRF)
    assert all(p.filter is not None for p in call["prefetch"])
    [hit] = hits
    assert (hit.scene_id, hit.movie_id, hit.score) == ("496243_backdrop_0", 13, 0.5)
    assert hit.attrs.country == "KR" and hit.attrs.decade == "2010s"


def test_search_plots_uses_movies_collection_and_top20() -> None:
    fake = FakeQdrant([_point(0.5, movie_id=13, country="KR")])
    [hit] = hybrid.search_plots(VECTORS, client=cast(QdrantClient, fake))
    call = fake.calls[0]
    assert call["collection_name"] == MOVIES_COLLECTION and call["limit"] == 20
    assert [p.using for p in call["prefetch"]] == ["plot_dense", "plot_sparse_ko"]
    assert hit.movie_id == 13


def test_retrieve_embeds_once(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []

    def fake_embed(texts: list[str], **_: Any) -> tuple[list[list[float]], CallStats]:
        calls.append(texts)
        return [[0.1, 0.2]], CallStats("m", 5, 0, 0.0, 1)

    monkeypatch.setattr("app.core.llm.embed", fake_embed)
    monkeypatch.setattr("app.search.sparse.tokenize", lambda text, kiwi=None: ["좀비"])
    fake = FakeQdrant([])
    result = hybrid.retrieve("좀비 기차", client=cast(QdrantClient, fake))
    assert calls == [["좀비 기차"]]
    assert len(fake.calls) == 2  # 장면 + 줄거리
    assert result.embed_stats is not None and result.embed_stats.input_tokens == 5
