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

# eval_runs 컬럼 중 그대로 돌려주는 것
COLUMNS = (
    "id",
    "split",
    "dataset_version",
    "recall_at_1",
    "recall_at_5",
    "mrr",
    "avg_clarify",
    "p95_latency_ms",
    "cost_per_query_usd",
)


def to_out(run: EvalRun) -> EvalRunOut:
    cfg = run.config or {}
    return EvalRunOut(
        **{c: getattr(run, c) for c in COLUMNS},
        experiment=str(cfg.get("experiment") or ""),
        name=str(cfg.get("name") or ""),
        agent=bool(cfg.get("agent")),
        commit=cfg.get("commit"),
    )


@router.get("/eval/runs")
def eval_runs() -> list[EvalRunOut]:
    with SessionLocal() as db:
        return [to_out(r) for r in db.scalars(select(EvalRun).order_by(EvalRun.id))]
