"""에이전트 그래프 흐름 테스트. LLM·Qdrant·DB는 가짜로 바꾸고 메모리 체크포인터를 쓴다."""

from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from app.agent.checkpoint import make_serde, psycopg_url
from app.agent.graph import build_graph, initial_state
from app.agent.movies import MovieInfo
from app.agent.nodes.clarify import answer_value
from app.agent.nodes.rewrite import valid_soft_filters
from app.agent.prompts import RewriteOutput, SoftFilterFields
from app.agent.state import Question
from app.core.llm import CallStats
from app.core.uploads import load_upload, save_upload
from app.search.caption import People, SceneCaption
from app.search.clarify import UNKNOWN, ClarifyOption
from app.search.confidence import Verified, VerifyOutput
from app.search.filters import MovieAttrs
from app.search.hybrid import RetrievalResult, SceneHit

MOVIES = {
    1: MovieInfo(
        movie_id=1,
        tmdb_id=101,
        title_ko="기생충",
        title_en="Parasite",
        year=2019,
        poster_url="p1",
        genres=["드라마"],
    ),
    2: MovieInfo(
        movie_id=2,
        tmdb_id=102,
        title_ko="올드보이",
        title_en="Oldboy",
        year=2003,
        poster_url="p2",
        genres=["스릴러"],
    ),
}
ATTRS = {
    1: MovieAttrs(year=2019, decade="2010s", country="KR", genres=["드라마"]),
    2: MovieAttrs(year=2003, decade="2000s", country="KR", genres=["드라마"]),
}
STATS = CallStats("m", 10, 5, 0.001, 1)


class Fakes:
    def __init__(self, verify_scores: Callable[[int], dict[int, float]]) -> None:
        self.verify_scores = verify_scores
        self.verify_calls = 0
        self.retrieve_calls: list[tuple[str, dict[str, str]]] = []
        self.chat_calls = 0

    def parse(self, messages: Any, fmt: type, **kw: Any) -> tuple[Any, CallStats]:
        if fmt is RewriteOutput:
            out = RewriteOutput(
                scene_ko="반지하 집에 물이 찬다",
                keywords_ko=["반지하", "홍수"],
                soft_filters=SoftFilterFields(
                    decade=None, country="KR", genre="없는장르", is_animation=None
                ),
            )
            return out, STATS
        if fmt is VerifyOutput:
            self.verify_calls += 1
            scores = self.verify_scores(self.verify_calls)
            items = [Verified(movie_id=m, score=s, reason=f"이유 {m}") for m, s in scores.items()]
            return VerifyOutput(items=items), STATS
        if fmt is SceneCaption:
            return SceneCaption(
                caption_ko="비 오는 밤 반지하 창문 너머로 물이 차오르는 집 안이 보인다.",
                caption_en="x",
                setting="반지하",
                time_of_day="night",
                weather="비",
                people=People(count=0, actions=[]),
                objects=["창문"],
                colors=["파란색"],
                text_in_frame=None,
            ), STATS
        raise AssertionError(fmt)

    def chat(self, messages: Any, **kw: Any) -> tuple[Any, CallStats]:
        self.chat_calls += 1
        msg = SimpleNamespace(content="언제쯤 개봉한 영화였나요?")
        return SimpleNamespace(choices=[SimpleNamespace(message=msg)]), STATS

    def retrieve(
        self, text: str, hard_filters: dict[str, str] | None = None, **_: Any
    ) -> RetrievalResult:
        self.retrieve_calls.append((text, dict(hard_filters or {})))
        hits = [
            SceneHit(
                scene_id=f"{m}_backdrop_0",
                movie_id=m,
                score=0.5 / m,
                caption_ko=f"장면 {m}",
                attrs=ATTRS[m],
            )
            for m in (1, 2)
            if not hard_filters
            or all(ATTRS[m].decade == v for k, v in hard_filters.items() if k == "decade")
        ]
        return RetrievalResult(scene_hits=hits, plot_hits=[], embed_stats=STATS)


@pytest.fixture
def run(monkeypatch: pytest.MonkeyPatch) -> Callable[..., tuple[Any, Fakes]]:
    def _run(verify_scores: Callable[[int], dict[int, float]]) -> tuple[Any, Fakes]:
        fakes = Fakes(verify_scores)
        monkeypatch.setattr("app.core.llm.parse", fakes.parse)
        monkeypatch.setattr("app.core.llm.chat", fakes.chat)
        monkeypatch.setattr("app.search.hybrid.retrieve", fakes.retrieve)
        monkeypatch.setattr("app.agent.movies.all_movies", lambda: MOVIES)
        graph = build_graph(InMemorySaver(serde=make_serde()))
        return graph, fakes

    return _run


CFG = {"configurable": {"thread_id": "s1"}}


def test_confident_answers_without_clarify(run: Callable[..., tuple[Any, Fakes]]) -> None:
    graph, fakes = run(lambda n: {1: 0.95, 2: 0.2})
    out = graph.invoke(initial_state("s1", "반지하에 물 차는 장면", None), CFG)
    assert "__interrupt__" not in out
    assert [r.movie_id for r in out["result"]] == [1, 2]
    top = out["result"][0]
    assert (top.title_ko, top.year, top.reason, top.score) == ("기생충", 2019, "이유 1", 0.95)
    assert top.evidence[0].scene_id == "1_backdrop_0"
    assert out["confidence"] >= 0.7 and out["clarify_turns"] == 0
    # rewrite: 형식이 맞는 soft filter만 남는다("없는장르"는 버림)
    assert out["rewritten"].soft_filters == {"country": "KR"}
    assert fakes.retrieve_calls == [("반지하 집에 물이 찬다 반지하 홍수", {})]
    # 노드별 비용이 합산된다: rewrite + retrieve(임베딩) + verify
    assert out["cost_usd"] == pytest.approx(0.003)
    assert {"rewrite_query", "retrieve", "verify", "answer"} <= set(out["timings_ms"])


def test_low_confidence_clarify_resume_applies_hard_filter(
    run: Callable[..., tuple[Any, Fakes]],
) -> None:
    graph, fakes = run(lambda n: {1: 0.6, 2: 0.55} if n == 1 else {1: 0.9})
    out = graph.invoke(initial_state("s1", "물 차는 집", None), CFG)
    [intr] = out["__interrupt__"]
    q = intr.value
    assert q["attr"] == "decade" and q["text"] == "언제쯤 개봉한 영화였나요?"
    assert [o["value"] for o in q["options"]] == ["2010s", "2000s", UNKNOWN]

    out = graph.invoke(Command(resume="2010s"), CFG)
    assert "__interrupt__" not in out
    assert fakes.retrieve_calls[-1][1] == {"decade": "2010s"}  # 두 번째 검색에 hard filter
    assert out["hard_filters"] == {"decade": "2010s"}
    assert out["asked_attrs"] == ["decade"] and out["clarify_turns"] == 1
    assert [r.movie_id for r in out["result"]] == [1]
    assert fakes.chat_calls == 1  # 재개해도 질문 생성(ask)은 다시 돌지 않는다


def test_stops_after_max_clarify_turns(
    run: Callable[..., tuple[Any, Fakes]], monkeypatch: pytest.MonkeyPatch
) -> None:
    # 연대·국가·장르가 모두 갈리고 계속 접전, 매번 "모르겠어요"
    # → 엔트로피 순서대로 2번 묻고(MAX_CLARIFY_TURNS=2) 세 번째는 묻지 않고 답한다
    other = MovieAttrs(year=2003, decade="2000s", country="US", genres=["스릴러"])
    monkeypatch.setitem(ATTRS, 2, other)
    graph, _ = run(lambda n: {1: 0.6, 2: 0.55})
    out = graph.invoke(initial_state("s1", "q", None), CFG)
    asked = []
    while "__interrupt__" in out:
        asked.append(out["__interrupt__"][0].value["attr"])
        out = graph.invoke(Command(resume=UNKNOWN), CFG)
    assert asked == ["decade", "country"]
    assert out["clarify_turns"] == 2 and out["result"]
    assert out["hard_filters"] == {}  # "모르겠어요"는 필터를 더하지 않는다


def test_no_clarify_when_attributes_do_not_split(
    run: Callable[..., tuple[Any, Fakes]], monkeypatch: pytest.MonkeyPatch
) -> None:
    same = MovieAttrs(year=2019, decade="2010s", country="KR", genres=["드라마"])
    monkeypatch.setitem(ATTRS, 2, same)
    graph, _ = run(lambda n: {1: 0.6, 2: 0.55})
    out = graph.invoke(initial_state("s1", "q", None), CFG)
    assert "__interrupt__" not in out and out["clarify_turns"] == 0  # 엔트로피 0 → 바로 답


def test_image_query_is_captioned_first(
    run: Callable[..., tuple[Any, Fakes]], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    key = save_upload(b"\xff\xd8jpeg", ".jpg", tmp_path)
    monkeypatch.setattr("app.agent.nodes.analyze.load_upload", lambda k: load_upload(k, tmp_path))
    graph, _ = run(lambda n: {1: 0.95})
    out = graph.invoke(initial_state("s1", None, key), CFG)
    assert out["image_caption"].setting == "반지하"
    assert out["result"][0].movie_id == 1


def test_answer_value_unknown_for_invalid_option() -> None:
    q = Question(attr="decade", text="?", options=[ClarifyOption(value="2010s", label="2010년대")])
    assert answer_value(q, "2010s") == "2010s"
    assert answer_value(q, "1990s") == UNKNOWN


def test_valid_soft_filters() -> None:
    fields = SoftFilterFields(decade="2000s", country="other", genre="액션", is_animation="true")
    assert valid_soft_filters(fields, ["액션"]) == {
        "decade": "2000s",
        "country": "other",
        "genre": "액션",
        "is_animation": "true",
    }
    bad = SoftFilterFields(decade="2000년대", country=None, genre="무협", is_animation=None)
    assert valid_soft_filters(bad, ["액션"]) == {}


def test_upload_rejects_bad_keys(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        save_upload(b"x", ".gif", tmp_path)
    with pytest.raises(ValueError):
        load_upload("../secret.jpg", tmp_path)


def test_psycopg_url() -> None:
    assert psycopg_url("postgresql+psycopg://a:b@h:5432/db") == "postgresql://a:b@h:5432/db"
