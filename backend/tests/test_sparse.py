import json
from pathlib import Path

import pytest
from kiwipiepy import Kiwi

from app.search import sparse


@pytest.fixture(scope="module")
def kiwi() -> Kiwi:
    # 사용자 사전 없이 Kiwi 기본 사전만 쓴다(테스트가 로컬 데이터에 기대지 않도록).
    return Kiwi()


def test_keep_tag_strips_conjugation_suffix() -> None:
    assert sparse.keep_tag("VV-R") and sparse.keep_tag("VA-I") and sparse.keep_tag("NNG")
    assert not sparse.keep_tag("JKS") and not sparse.keep_tag("EF") and not sparse.keep_tag("NNB")


def test_tokenize_keeps_spec_pos_and_stems(kiwi: Kiwi) -> None:
    tokens = sparse.tokenize("비 오는 밤 가족이 피자 상자를 접는다", kiwi)
    assert tokens == ["비", "오", "밤", "가족", "피자", "상자", "접"]


def test_tokenize_irregular_adjective_and_english_lowercase(kiwi: Kiwi) -> None:
    tokens = sparse.tokenize("파란 하늘 아래 3명이 TV를 본다", kiwi)
    assert "파랗" in tokens  # VA-I
    assert "tv" in tokens and "TV" not in tokens  # SL은 소문자
    assert "3" in tokens  # SN


def test_term_id_is_unsigned_mmh3() -> None:
    assert sparse.term_id("기차") == sparse.term_id("기차")
    assert 0 <= sparse.term_id("기차") < 2**32
    assert sparse.term_id("기차") != sparse.term_id("좀비")


def test_doc_vector_bm25_formula() -> None:
    tokens = ["좀비", "좀비", "기차"]
    vec = sparse.doc_vector(tokens, avgdl=3.0)
    by_id = dict(zip(vec.indices, vec.values, strict=True))
    norm = 1.2 * (1 - 0.75 + 0.75 * 3 / 3.0)  # dl == avgdl → norm = k1
    assert by_id[sparse.term_id("좀비")] == pytest.approx(2 * 2.2 / (2 + norm))
    assert by_id[sparse.term_id("기차")] == pytest.approx(1 * 2.2 / (1 + norm))
    assert vec.indices == sorted(vec.indices)


def test_doc_vector_longer_doc_gets_lower_weight() -> None:
    short = sparse.doc_vector(["좀비"], avgdl=5.0)
    long = sparse.doc_vector(["좀비"] + ["기차"] * 9, avgdl=5.0)
    assert long.values[long.indices.index(sparse.term_id("좀비"))] < short.values[0]


def test_doc_vector_empty() -> None:
    assert sparse.doc_vector([], avgdl=5.0) == sparse.SparseVector([], [])


def test_query_vector_unique_ones() -> None:
    vec = sparse.query_vector(["좀비", "좀비", "기차"])
    assert len(vec.indices) == 2 and vec.values == [1.0, 1.0]


def test_bm25_stats_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "bm25_stats.json"
    sparse.save_bm25_stats({"scenes": {"avgdl": 12.5, "n_docs": 3}}, path)
    assert sparse.load_avgdl("scenes", path) == 12.5
    assert json.loads(path.read_text(encoding="utf-8"))["scenes"]["n_docs"] == 3
