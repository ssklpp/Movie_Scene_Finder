"""GET /eval/runs: 내부 평가 대시보드(SPEC §10 `/eval`)가 읽는 eval_runs 목록.

실험 이름·설정 이름·커밋은 config JSON에서 꺼내 평평하게 돌려준다. 배포 DB에는
scripts/copy_eval_runs.sh로 로컬의 eval_runs를 복사한다.
"""

from fastapi import APIRouter
from sqlalchemy import select

from app.api.schemas import EvalRunOut
from app.db.models import EvalRun
from app.db.session import SessionLocal

router = APIRouter()


def to_out(run: EvalRun) -> EvalRunOut:
    cfg = run.config or {}
    return EvalRunOut(
        id=run.id,
        experiment=str(cfg.get("experiment") or ""),
        name=str(cfg.get("name") or ""),
        split=run.split or "",
        dataset_version=run.dataset_version,
        agent=bool(cfg.get("agent")),
        recall_at_1=run.recall_at_1,
        recall_at_5=run.recall_at_5,
        mrr=run.mrr,
        clarify_success=run.clarify_success,
        avg_clarify=run.avg_clarify,
        p95_latency_ms=run.p95_latency_ms,
        cost_per_query_usd=run.cost_per_query_usd,
        commit=cfg.get("commit"),
        created_at=run.created_at,
    )


@router.get("/eval/runs")
def eval_runs() -> list[EvalRunOut]:
    with SessionLocal() as db:
        return [to_out(r) for r in db.scalars(select(EvalRun).order_by(EvalRun.id))]
