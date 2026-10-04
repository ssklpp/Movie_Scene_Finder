"""실험 비교표: eval_runs에서 실험별 설정(name)마다 최신 결과를 모아 Markdown 표로 출력한다.

uv run python -m eval.report --experiment E1 --split dev
"""

import argparse
from collections.abc import Sequence

from sqlalchemy import select

from app.db.models import EvalRun
from app.db.session import SessionLocal


def latest_per_name(runs: Sequence[EvalRun]) -> list[EvalRun]:
    """같은 설정 이름이면 가장 최근(id가 큰) 실행만 남긴다. 이름 순으로 돌려준다."""
    latest: dict[str, EvalRun] = {}
    for run in runs:
        name = str((run.config or {}).get("name"))
        if name not in latest or run.id > latest[name].id:
            latest[name] = run
    return [latest[k] for k in sorted(latest)]


def fmt(value: float | None, digits: int) -> str:
    """값이 없으면(검색만 평가한 실행의 재질문 지표 등) "-"."""
    return "-" if value is None else f"{value:.{digits}f}"


def comparison_table(runs: Sequence[EvalRun]) -> str:
    lines = [
        "| 설정 | Recall@1 | Recall@5 | MRR | 평균 재질문 | clarify_success | p95 (ms) "
        "| 질의당 비용 (USD) | 데이터 | 커밋 | run id |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for r in runs:
        cfg = r.config or {}
        lines.append(
            f"| {cfg.get('name')} | {fmt(r.recall_at_1, 3)} | {fmt(r.recall_at_5, 3)} "
            f"| {fmt(r.mrr, 3)} | {fmt(r.avg_clarify, 2)} | {fmt(r.clarify_success, 3)} "
            f"| {r.p95_latency_ms} | {fmt(r.cost_per_query_usd, 6)} "
            f"| {r.dataset_version} | {cfg.get('commit')} | {r.id} |"
        )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--experiment", required=True)
    parser.add_argument("--split", choices=["dev", "test"], default="dev")
    args = parser.parse_args()
    with SessionLocal() as session:
        stmt = select(EvalRun).where(
            EvalRun.split == args.split,
            EvalRun.config["experiment"].astext == args.experiment,
        )
        runs = latest_per_name(list(session.scalars(stmt)))
    print(f"## {args.experiment} ({args.split})\n")
    print(comparison_table(runs))


if __name__ == "__main__":
    main()
