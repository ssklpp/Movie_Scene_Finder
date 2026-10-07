from pathlib import Path
from typing import Any

import pytest

from app.core.llm import CallStats
from pipeline.s07_embed import (
    embed_with_cache,
    load_dense_cache,
    movie_doc,
    text_hash,
    write_parquet,
)


def test_text_hash_depends_on_model_and_dim() -> None:
    assert text_hash("a", "m", 1536) == text_hash("a", "m", 1536)
    assert text_hash("a", "m", 1536) != text_hash("a", "m", 512)
    assert text_hash("a", "m", 1536) != text_hash("a", "n", 1536)


def test_embed_with_cache_only_embeds_missing_in_batches(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []

    def fake_embed(texts: list[str], **_: Any) -> tuple[list[list[float]], CallStats]:
        calls.append(texts)
        return [[float(len(t))] for t in texts], CallStats("m", len(texts), 0, 0.001, 1)

    monkeypatch.setattr("app.core.llm.embed", fake_embed)
    texts = ["a", "bb", "ccc", "dddd", "eeeee"]
    hashes = [f"h{i}" for i in range(5)]
    cache = {"h1": [99.0]}
    vectors, new, cost = embed_with_cache(texts, hashes, cache, batch=2)
    assert calls == [["a", "ccc"], ["dddd", "eeeee"]]
    assert vectors == [[1.0], [99.0], [3.0], [4.0], [5.0]]
    assert new == 4 and cost == pytest.approx(0.002)


def test_parquet_roundtrip_reuses_dense(tmp_path: Path) -> None:
    path = tmp_path / "scenes.parquet"
    write_parquet(
        path,
        {
            "scene_id": ["s1", "s2"],
            "text_hash": ["h1", "h2"],
            "dense": [[0.5, 1.0], [2.0, 3.0]],
            "sparse_indices": [[1, 4000000000], []],
            "sparse_values": [[0.5, 1.5], []],
        },
        dim=2,
    )
    assert load_dense_cache(path) == {"h1": [0.5, 1.0], "h2": [2.0, 3.0]}
    assert not path.with_suffix(".part").exists()


def test_movie_doc_appends_keywords() -> None:
    assert movie_doc("줄거리", ["양궁", "한강"]) == "줄거리\n양궁, 한강"
    assert movie_doc("줄거리", None) == "줄거리"
    assert movie_doc(None, ["양궁"]) == "양궁"
    assert movie_doc(None, []) == ""
