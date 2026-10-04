from collections import Counter
from typing import Any

import pytest
from kiwipiepy import Kiwi

from app.core.llm import CallStats
from eval import make_synthetic as ms


@pytest.fixture(autouse=True)
def _plain_kiwi(monkeypatch: pytest.MonkeyPatch) -> None:
    # 로컬 사용자 사전 없이 Kiwi 기본 사전만 쓴다.
    kiwi = Kiwi()
    monkeypatch.setattr("app.search.sparse.get_kiwi", lambda *a: kiwi)


ROWS = [
    (f"{m}_backdrop_{n}", m, 1000 + m, f"영화 {m} 장면 {n}") for m in range(1, 11) for n in range(3)
]


def test_pick_sources_one_scene_per_movie_and_split() -> None:
    sources = ms.pick_sources(ROWS, seed=0, dev_size=7)
    assert len(sources) == 10
    assert len({s.movie_id for s in sources}) == 10
    assert Counter(s.split for s in sources) == {"dev": 7, "test": 3}
    assert [s.id for s in sources] == [f"syn-{i:04d}" for i in range(1, 11)]
    assert all(s.tmdb_id == 1000 + s.movie_id for s in sources)


def test_pick_sources_is_deterministic() -> None:
    assert ms.pick_sources(ROWS, 0, 7) == ms.pick_sources(list(reversed(ROWS)), 0, 7)
    assert ms.pick_sources(ROWS, 0, 7) != ms.pick_sources(ROWS, 1, 7)


def test_token_overlap() -> None:
    src = "비 오는 밤 골목에서 남자가 우산을 쓰고 걷는다"
    assert ms.token_overlap(src, src) == 1.0
    assert ms.token_overlap(src, "햇살 좋은 낮 바닷가") == 0.0
    assert 0 < ms.token_overlap(src, "밤에 남자가 뛰어가던 장면") < 1
    assert ms.token_overlap("", "아무거나") == 0.0


def _source() -> ms.Source:
    return ms.Source(
        "syn-0001", "1_backdrop_0", 1, 1001, "비 오는 밤 골목에서 남자가 우산을 쓰고 걷는다", "dev"
    )


def test_generate_retries_until_overlap_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    replies = iter(
        [
            ms.SyntheticQuery(
                query="비 오는 밤 골목에서 남자가 우산을 쓰고 걷는", distorted_detail="x"
            ),
            ms.SyntheticQuery(
                query="눈 오던 저녁에 어떤 아저씨가 길을 가던 영화", distorted_detail="비→눈"
            ),
        ]
    )
    calls: list[dict[str, Any]] = []

    def fake_parse(messages: Any, fmt: Any, **kw: Any) -> tuple[ms.SyntheticQuery, CallStats]:
        calls.append(kw)
        return next(replies), CallStats("sol", 100, 50, 0.001, 1)

    monkeypatch.setattr("app.core.llm.parse", fake_parse)
    record, cost = ms.generate(_source(), "sol")
    assert len(calls) == 2 and calls[0]["model"] == "sol"
    assert calls[0]["reasoning_effort"] == "low"
    assert record is not None and record["distorted_detail"] == "비→눈"
    assert record["overlap"] <= ms.MAX_OVERLAP
    assert cost == pytest.approx(0.002)
    assert {k: record[k] for k in ("id", "answer_movie_id", "answer_tmdb_id", "split")} == {
        "id": "syn-0001",
        "answer_movie_id": 1,
        "answer_tmdb_id": 1001,
        "split": "dev",
    }
    assert record["source"] == "synthetic" and record["image_path"] is None


def test_generate_keeps_best_when_all_attempts_overlap(monkeypatch: pytest.MonkeyPatch) -> None:
    same = ms.SyntheticQuery(
        query="비 오는 밤 골목에서 남자가 우산을 쓰고 걷는다", distorted_detail="x"
    )

    def fake_parse(*a: Any, **kw: Any) -> tuple[ms.SyntheticQuery, CallStats]:
        return same, CallStats("sol", 1, 1, 0.0, 1)

    monkeypatch.setattr("app.core.llm.parse", fake_parse)
    record, _ = ms.generate(_source(), "sol")
    assert record is not None and record["overlap"] == 1.0


def test_generate_returns_none_when_every_call_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*a: Any, **kw: Any) -> Any:
        raise RuntimeError("api down")

    monkeypatch.setattr("app.core.llm.parse", boom)
    assert ms.generate(_source(), "sol") == (None, 0.0)
