from pathlib import Path
from typing import Any

from kiwipiepy import Kiwi

from pipeline.build_user_dict import (
    build_entries,
    credit_names,
    name_words,
    title_words,
    write_user_dict,
)


def test_title_words_only_single_hangul_word() -> None:
    assert title_words("기생충") == ["기생충"]
    assert title_words("후궁: 제왕의 첩") == []
    assert title_words("범죄도시4") == []
    assert title_words("Toy Story") == []
    assert title_words(None) == []


def test_name_words_splits_and_drops_short_or_latin_parts() -> None:
    assert name_words("송강호") == ["송강호"]
    assert name_words("레오나르도 디카프리오") == ["레오나르도", "디카프리오"]
    assert name_words("톰 하디") == ["하디"]
    assert name_words("조셉 고든레빗") == ["조셉", "고든레빗"]
    assert name_words("Tom Hardy") == []


def test_credit_names_top_cast_by_order_plus_directors() -> None:
    credits: dict[str, Any] = {
        "cast": [{"name": f"배우{i}", "order": i} for i in (2, 0, 1)],
        "crew": [{"name": "봉준호", "job": "Director"}, {"name": "작가", "job": "Writer"}],
    }
    assert credit_names(credits, top_cast=2) == ["배우0", "배우1", "봉준호"]


def test_build_entries_dedup_sorted_nnp() -> None:
    entries = build_entries(["기생충", "기생충", "후궁: 제왕의 첩"], ["봉준호", "송강호"])
    assert entries == ["기생충\tNNP", "봉준호\tNNP", "송강호\tNNP"]


def test_kiwi_loads_dict_and_keeps_name_as_one_token(tmp_path: Path) -> None:
    path = tmp_path / "user_dict.txt"
    write_user_dict(build_entries([], ["디카프리오"]), path)
    kiwi = Kiwi()
    assert kiwi.load_user_dictionary(str(path)) == 1
    tokens = [(t.form, t.tag) for t in kiwi.tokenize("디카프리오가 배에서 소리친다")]
    assert ("디카프리오", "NNP") in tokens
