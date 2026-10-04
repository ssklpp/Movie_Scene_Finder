"""검색·에이전트 평가 (SPEC §11).

    uv run python -m eval.run_eval --config eval/configs/E1_hybrid.yaml --split dev --no-agent
    uv run python -m eval.run_eval --config eval/configs/E6_turns2.yaml --split dev

- 데이터셋: eval/datasets/{synthetic,human}_v1.jsonl 중 split이 맞는 레코드
  (dev = synthetic dev 200, test = synthetic test 100 + human).
- --no-agent: 질의를 그대로 retrieve → aggregate 한다(재작성·검증·재질문 없음).
- 에이전트 모드(--no-agent 없이, 설정 agent: true): 에이전트 그래프 전체를 메모리 체크포인터로
  돌리고, 재질문에는 시뮬레이터(eval/simulator.py)가 정답 영화의 속성으로 답한다. sessions에는
  기록하지 않는다. 설정의 max_clarify_turns·confidence_threshold로 .env 값을 덮어쓴다(E6).
- 정답은 answer_tmdb_id로 맞춘다(movies.id는 DB를 새로 만들면 바뀔 수 있다).
- 지표: 상위 MOVIE_TOPK 안의 정답 순위로 Recall@1·@5·MRR(10위 밖은 0), 지연시간 p95,
  질의당 비용. 에이전트 모드는 평균 재질문 횟수(avg_clarify)와 clarify_success(재질문을 한 질의 중
  최종 1위가 정답인 비율, SPEC에 정의가 없어 이렇게 정함)를 더하고, p95는 요청 1회(사용자가 응답을
  기다리는 단위) 기준이다. 질의를 동시에 돌리므로(--workers) 지연시간은 다소 높게 잡힌다.
- 결과는 eval_runs에 기록하고 reports/eval_{시각}_*.md와 상세 jsonl을 쓴다.
"""

import argparse
import json
import logging
import math
import subprocess
import time
import uuid
from collections.abc import Iterable, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command
from pydantic import BaseModel
from sqlalchemy import select

from app.agent.checkpoint import make_serde
from app.agent.graph import build_graph, initial_state
from app.core.config import REPO_ROOT, get_settings
from app.core.logging import setup_logging
from app.db.models import EvalRun, Movie
from app.db.session import SessionLocal
from app.search.aggregate import aggregate
from app.search.filters import MovieAttrs
from app.search.hybrid import Mode, retrieve
from app.search.qdrant import decade_key
from eval.simulator import simulated_answer

logger = logging.getLogger(__name__)

DATASETS_DIR = REPO_ROOT / "eval" / "datasets"
REPORTS_DIR = REPO_ROOT / "reports"
DATASET_FILES = {"synthetic": "synthetic_v1.jsonl", "human": "human_v1.jsonl"}
MAX_AGENT_REQUESTS = 6  # 재질문이 끝나지 않는 경우를 막는 안전장치


class EvalConfig(BaseModel):
    experiment: str
    name: str
    mode: Mode = "hybrid"
    agent: bool = False
    # 비워 두면 .env 값을 쓴다
    w_second_scene: float | None = None
    w_plot: float | None = None
    soft_filter_boost: float | None = None
    movie_topk: int | None = None
    max_clarify_turns: int | None = None  # 에이전트 모드만
    confidence_threshold: float | None = None  # 에이전트 모드만


@dataclass(frozen=True)
class Example:
    id: str
    dataset: str
    query: str
    answer_tmdb_id: int


@dataclass(frozen=True)
class QueryResult:
    id: str
    dataset: str
    query: str
    answer_tmdb_id: int
    rank: int | None  # 1부터. 상위 목록에 없으면 None
    top_tmdb_ids: list[int]
    latency_ms: int  # 질의 전체 처리 시간
    cost_usd: float
    clarify_turns: int = 0
    request_latencies_ms: list[int] = field(default_factory=list)  # 에이전트: 요청(invoke)별


@dataclass(frozen=True)
class Metrics:
    n: int
    recall_at_1: float
    recall_at_5: float
    mrr: float


def load_config(path: Path) -> EvalConfig:
    return EvalConfig.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


def load_examples(
    split: str, datasets: Iterable[str], datasets_dir: Path = DATASETS_DIR
) -> list[Example]:
    examples = []
    for name in datasets:
        path = datasets_dir / DATASET_FILES[name]
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            r = json.loads(line)
            if r["split"] == split:
                examples.append(Example(r["id"], name, r["query"], int(r["answer_tmdb_id"])))
    return examples


def rank_of(answer: int, ranked: Sequence[int]) -> int | None:
    return ranked.index(answer) + 1 if answer in ranked else None


def compute_metrics(ranks: Sequence[int | None]) -> Metrics:
    n = len(ranks)
    if n == 0:
        return Metrics(0, 0.0, 0.0, 0.0)
    return Metrics(
        n=n,
        recall_at_1=sum(r == 1 for r in ranks) / n,
        recall_at_5=sum(r is not None and r <= 5 for r in ranks) / n,
        mrr=sum(1 / r for r in ranks if r is not None) / n,
    )


def percentile(values: Sequence[float], p: float) -> float:
    """nearest-rank 백분위수."""
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[max(math.ceil(p / 100 * len(ordered)) - 1, 0)]


def run_query(ex: Example, cfg: EvalConfig, tmdb_by_movie: dict[int, int]) -> QueryResult:
    started = time.perf_counter()
    result = retrieve(ex.query, mode=cfg.mode)
    ranked = aggregate(
        result.scene_hits,
        result.plot_hits,
        w_second_scene=cfg.w_second_scene,
        w_plot=cfg.w_plot,
        soft_filter_boost=cfg.soft_filter_boost,
        movie_topk=cfg.movie_topk,
    )
    latency_ms = round((time.perf_counter() - started) * 1000)
    top = [tmdb_by_movie[m.movie_id] for m in ranked]
    return QueryResult(
        id=ex.id,
        dataset=ex.dataset,
        query=ex.query,
        answer_tmdb_id=ex.answer_tmdb_id,
        rank=rank_of(ex.answer_tmdb_id, top),
        top_tmdb_ids=top,
        latency_ms=latency_ms,
        cost_usd=result.embed_stats.cost_usd if result.embed_stats else 0.0,
    )


def movie_attrs(movie: Movie) -> MovieAttrs:
    return MovieAttrs(
        year=movie.year,
        decade=decade_key(movie.year),
        country=movie.country,
        genres=movie.genres or [],
        is_animation=bool(movie.is_animation),
    )


def run_agent_query(ex: Example, answer: MovieAttrs, tmdb_by_movie: dict[int, int]) -> QueryResult:
    """에이전트를 끝까지 돌린다. 재질문에는 시뮬레이터가 정답 영화의 속성으로 답한다."""
    graph = build_graph(InMemorySaver(serde=make_serde()))
    session_id = str(uuid.uuid4())
    config: RunnableConfig = {"configurable": {"thread_id": session_id}}
    graph_input: Any = initial_state(session_id, ex.query, None)
    latencies: list[int] = []
    out: dict[str, Any] = {}
    for _ in range(MAX_AGENT_REQUESTS):
        started = time.perf_counter()
        out = graph.invoke(graph_input, config)
        latencies.append(round((time.perf_counter() - started) * 1000))
        if "__interrupt__" not in out:
            break
        graph_input = Command(resume=simulated_answer(out["__interrupt__"][0].value, answer))
    top = [tmdb_by_movie[r.movie_id] for r in out.get("result") or []]
    return QueryResult(
        id=ex.id,
        dataset=ex.dataset,
        query=ex.query,
        answer_tmdb_id=ex.answer_tmdb_id,
        rank=rank_of(ex.answer_tmdb_id, top),
        top_tmdb_ids=top,
        latency_ms=sum(latencies),
        cost_usd=float(out.get("cost_usd", 0.0)),
        clarify_turns=int(out.get("clarify_turns", 0)),
        request_latencies_ms=latencies,
    )


def clarify_stats(results: Sequence[QueryResult]) -> tuple[float | None, float]:
    """(clarify_success, avg_clarify). 재질문을 한 질의가 없으면 clarify_success는 None."""
    asked = [r for r in results if r.clarify_turns > 0]
    success = sum(r.rank == 1 for r in asked) / len(asked) if asked else None
    avg = sum(r.clarify_turns for r in results) / len(results) if results else 0.0
    return success, avg


def apply_overrides(cfg: EvalConfig) -> None:
    """에이전트가 읽는 설정(.env)을 실험 설정으로 덮어쓴다(이 프로세스 안에서만)."""
    settings = get_settings()
    if cfg.max_clarify_turns is not None:
        settings.max_clarify_turns = cfg.max_clarify_turns
    if cfg.confidence_threshold is not None:
        settings.confidence_threshold = cfg.confidence_threshold


def git_commit() -> str:
    """현재 커밋 해시.

    코드(backend·pipeline·eval)에 커밋하지 않은 변경이 있으면 "-dirty"를 붙인다.
    """

    def git(*args: str) -> str:
        out = subprocess.run(["git", *args], cwd=REPO_ROOT, capture_output=True, text=True)
        return out.stdout.strip()

    try:
        commit = git("rev-parse", "--short", "HEAD") or "unknown"
        dirty = git("status", "--porcelain", "--", "backend", "pipeline", "eval")
    except OSError:
        return "unknown"
    return f"{commit}-dirty" if dirty else commit


def metrics_table(rows: Iterable[tuple[str, Metrics]]) -> list[str]:
    lines = ["| 데이터셋 | n | Recall@1 | Recall@5 | MRR |", "| --- | --- | --- | --- | --- |"]
    for name, m in rows:
        lines.append(
            f"| {name} | {m.n} | {m.recall_at_1:.3f} | {m.recall_at_5:.3f} | {m.mrr:.3f} |"
        )
    return lines


def write_report(
    path: Path,
    cfg: EvalConfig,
    split: str,
    results: Sequence[QueryResult],
    titles: dict[int, str],
    run_info: dict[str, Any],
) -> None:
    by_dataset = sorted({r.dataset for r in results})
    rows = [("전체", compute_metrics([r.rank for r in results]))]
    rows += [(d, compute_metrics([r.rank for r in results if r.dataset == d])) for d in by_dataset]
    info = run_info
    lines = [
        f"# 평가 {cfg.experiment} / {cfg.name} ({split})",
        "",
        f"- 실행: {info['started_at']}, 커밋 `{info['commit']}`, eval_runs id {info['run_id']}",
        f"- 설정: `{json.dumps(cfg.model_dump(), ensure_ascii=False)}`",
        f"- 지연시간 p95 {info['p95_latency_ms']}ms ({info['latency_basis']})",
        f"- 질의당 비용 ${info['cost_per_query_usd']:.6f}",
    ]
    if cfg.agent:
        lines.append(
            f"- 평균 재질문 {info['avg_clarify']:.2f}회, clarify_success {info['clarify_success']}"
        )
    lines += [
        "",
        *metrics_table(rows),
        "",
        "## 1위가 아닌 질의",
        "",
        "| id | 질의 | 정답 | 순위 | 재질문 | 예측 1~3위 |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for r in sorted(results, key=lambda r: (r.rank or 999, r.id), reverse=True):
        if r.rank == 1:
            continue
        top3 = ", ".join(titles.get(t, str(t)) for t in r.top_tmdb_ids[:3])
        rank = r.rank if r.rank is not None else "-"
        query = r.query.replace("|", "/")
        answer = titles.get(r.answer_tmdb_id, str(r.answer_tmdb_id))
        lines.append(f"| {r.id} | {query} | {answer} | {rank} | {r.clarify_turns} | {top3} |")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--split", choices=["dev", "test"], default="dev")
    parser.add_argument("--datasets", default="synthetic,human", help="쉼표로 구분")
    parser.add_argument("--no-agent", action="store_true", help="에이전트 없이 검색만 평가")
    parser.add_argument("--limit", type=int, help="앞 N개 질의만(시험용, eval_runs에 기록 안 함)")
    parser.add_argument("--workers", type=int, help="동시 질의 수(기본: 에이전트 4, 검색만 1)")
    args = parser.parse_args()
    setup_logging()
    for noisy in ("httpx", "httpx2", "app.core.llm", "app.search.sparse", "app.agent"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    cfg = load_config(args.config)
    if cfg.agent == args.no_agent:
        raise SystemExit(f"config agent={cfg.agent}: use --no-agent only with agent: false")
    apply_overrides(cfg)

    examples = load_examples(args.split, args.datasets.split(","))[: args.limit]
    with SessionLocal() as session:
        movies = list(session.scalars(select(Movie)))
    tmdb_by_movie = {m.id: m.tmdb_id for m in movies}
    attrs_by_tmdb = {m.tmdb_id: movie_attrs(m) for m in movies}
    titles = {m.tmdb_id: m.title_ko or m.title_en or str(m.tmdb_id) for m in movies}
    logger.info(
        "eval %s/%s split=%s: %d queries", cfg.experiment, cfg.name, args.split, len(examples)
    )

    def one(ex: Example) -> QueryResult:
        if cfg.agent:
            return run_agent_query(ex, attrs_by_tmdb[ex.answer_tmdb_id], tmdb_by_movie)
        return run_query(ex, cfg, tmdb_by_movie)

    started_at = datetime.now().astimezone()
    results: list[QueryResult] = []
    workers = args.workers or (4 if cfg.agent else 1)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for i, r in enumerate(pool.map(one, examples), 1):
            results.append(r)
            if i % 20 == 0:
                logger.info("progress %d/%d", i, len(examples))

    overall = compute_metrics([r.rank for r in results])
    if cfg.agent:
        latencies = [ms for r in results for ms in r.request_latencies_ms]
        latency_basis = f"요청 1회 기준, 동시 {workers}개"
        clarify_success, avg_clarify = clarify_stats(results)
    else:
        latencies = [r.latency_ms for r in results]
        latency_basis = "질의 1개 기준"
        clarify_success, avg_clarify = None, None
    p95 = round(percentile(latencies, 95))
    cost_per_query = sum(r.cost_usd for r in results) / max(len(results), 1)
    commit = git_commit()
    dataset_version = "+".join(sorted({f"{r.dataset}_v1" for r in results}))

    run_id: int | None = None
    if args.limit is None:
        with SessionLocal.begin() as session:
            run = EvalRun(
                dataset_version=dataset_version,
                split=args.split,
                config={**cfg.model_dump(), "commit": commit, "workers": workers},
                recall_at_1=overall.recall_at_1,
                recall_at_5=overall.recall_at_5,
                mrr=overall.mrr,
                clarify_success=clarify_success,
                avg_clarify=avg_clarify,
                p95_latency_ms=p95,
                cost_per_query_usd=cost_per_query,
            )
            session.add(run)
            session.flush()
            run_id = run.id

    REPORTS_DIR.mkdir(exist_ok=True)
    stamp = started_at.strftime("%Y%m%d_%H%M%S")
    report_path = REPORTS_DIR / f"eval_{stamp}_{cfg.experiment}_{cfg.name}_{args.split}.md"
    run_info = {
        "started_at": started_at.isoformat(timespec="seconds"),
        "commit": commit,
        "run_id": run_id,
        "p95_latency_ms": p95,
        "latency_basis": latency_basis,
        "cost_per_query_usd": cost_per_query,
        "avg_clarify": avg_clarify,
        "clarify_success": clarify_success,
    }
    write_report(report_path, cfg, args.split, results, titles, run_info)
    details = report_path.with_suffix(".jsonl")
    details.write_text(
        "".join(json.dumps(asdict(r), ensure_ascii=False) + "\n" for r in results),
        encoding="utf-8",
    )
    logger.info(
        "eval done: n=%d R@1=%.3f R@5=%.3f MRR=%.3f p95=%dms cost/q=$%.6f "
        "avg_clarify=%s clarify_success=%s run_id=%s -> %s",
        overall.n,
        overall.recall_at_1,
        overall.recall_at_5,
        overall.mrr,
        p95,
        cost_per_query,
        avg_clarify,
        clarify_success,
        run_id,
        report_path.name,
    )


if __name__ == "__main__":
    main()
