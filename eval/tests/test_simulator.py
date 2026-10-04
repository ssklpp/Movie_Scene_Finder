from pathlib import Path

from app.search.clarify import UNKNOWN
from app.search.filters import MovieAttrs
from eval.run_eval import QueryResult, clarify_stats, load_config
from eval.simulator import simulated_answer

PARASITE = MovieAttrs(year=2019, decade="2010s", country="KR", genres=["코미디", "스릴러"])


def question(attr: str, *values: str) -> dict[str, object]:
    options = [{"value": v, "label": v} for v in [*values, UNKNOWN]]
    return {"attr": attr, "text": "?", "options": options}


def test_simulator_answers_with_true_attribute() -> None:
    assert simulated_answer(question("decade", "2000s", "2010s"), PARASITE) == "2010s"
    assert simulated_answer(question("country", "KR", "other"), PARASITE) == "KR"
    assert simulated_answer(question("genre", "코미디", "액션"), PARASITE) == "코미디"  # 대표 장르
    assert simulated_answer(question("is_animation", "true", "false"), PARASITE) == "false"


def test_simulator_says_unknown_when_truth_not_in_options() -> None:
    assert simulated_answer(question("decade", "1990s", "2000s"), PARASITE) == UNKNOWN
    assert simulated_answer(question("genre", "스릴러", "드라마"), PARASITE) == UNKNOWN
    assert simulated_answer(question("decade", "2010s"), MovieAttrs()) == UNKNOWN


def _result(rank: int | None, turns: int) -> QueryResult:
    return QueryResult("q", "synthetic", "q", 1, rank, [], 0, 0.0, clarify_turns=turns)


def test_clarify_stats() -> None:
    results = [_result(1, 0), _result(1, 1), _result(3, 2), _result(None, 1)]
    success, avg = clarify_stats(results)
    assert success == 1 / 3  # 재질문한 3개 중 1위 1개
    assert avg == (0 + 1 + 2 + 1) / 4
    assert clarify_stats([_result(1, 0)]) == (None, 0.0)


def test_e6_configs() -> None:
    configs = Path(__file__).resolve().parents[1] / "configs"
    turns = [load_config(configs / f"E6_turns{n}.yaml") for n in (0, 1, 2)]
    assert [c.max_clarify_turns for c in turns] == [0, 1, 2]
    assert all(c.agent and c.experiment == "E6" for c in turns)
