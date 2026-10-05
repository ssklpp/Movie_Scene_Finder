from datetime import UTC, datetime

from app.api.routes_eval import to_out
from app.db.models import EvalRun


def test_to_out_flattens_config() -> None:
    created = datetime(2026, 10, 5, tzinfo=UTC)
    run = EvalRun(
        id=7,
        split="dev",
        dataset_version="synthetic_v1",
        config={"experiment": "E6", "name": "turns2", "agent": True, "commit": "abc1234"},
        recall_at_1=0.86,
        recall_at_5=0.87,
        mrr=0.864,
        clarify_success=0.42,
        avg_clarify=0.3,
        p95_latency_ms=8400,
        cost_per_query_usd=0.00062,
        created_at=created,
    )
    out = to_out(run)
    assert (out.experiment, out.name, out.agent, out.commit) == ("E6", "turns2", True, "abc1234")
    assert out.recall_at_1 == 0.86 and out.p95_latency_ms == 8400


def test_to_out_handles_missing_config() -> None:
    run = EvalRun(id=1, split="dev", config=None, created_at=datetime(2026, 10, 5, tzinfo=UTC))
    out = to_out(run)
    assert (out.experiment, out.name, out.agent, out.commit) == ("", "", False, None)
    assert out.recall_at_1 is None
