import json
from pathlib import Path

import pytest

from app.db.models import EvalRun
from eval.report import comparison_table, latest_per_name
from eval.run_eval import (
    EvalConfig,
    compute_metrics,
    load_config,
    load_examples,
    percentile,
    rank_of,
)

CONFIGS = Path(__file__).resolve().parents[1] / "configs"


def test_e1_configs_load() -> None:
    modes = {load_config(CONFIGS / f"E1_{m}.yaml").mode for m in ("dense", "sparse", "hybrid")}
    assert modes == {"dense", "sparse", "hybrid"}
    cfg = load_config(CONFIGS / "E1_hybrid.yaml")
    assert cfg.experiment == "E1" and not cfg.agent and cfg.w_plot is None


def test_config_rejects_unknown_mode(tmp_path: Path) -> None:
    path = tmp_path / "bad.yaml"
    path.write_text("experiment: X\nname: x\nmode: bm25\n", encoding="utf-8")
    with pytest.raises(ValueError):
        load_config(path)


def test_load_examples_filters_split_and_skips_missing(tmp_path: Path) -> None:
    rows = [
        {"id": "syn-1", "query": "q1", "answer_tmdb_id": 10, "split": "dev"},
        {"id": "syn-2", "query": "q2", "answer_tmdb_id": 20, "split": "test"},
    ]
    (tmp_path / "synthetic_v1.jsonl").write_text(
        "".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8"
    )
    examples = load_examples("dev", ["synthetic", "human"], tmp_path)  # human 파일은 없다
    assert [(e.id, e.dataset, e.answer_tmdb_id) for e in examples] == [("syn-1", "synthetic", 10)]


def test_rank_of() -> None:
    assert rank_of(5, [3, 5, 7]) == 2
    assert rank_of(9, [3, 5, 7]) is None


def test_compute_metrics() -> None:
    m = compute_metrics([1, 2, 6, None])
    assert m.n == 4
    assert m.recall_at_1 == 0.25
    assert m.recall_at_5 == 0.5
    assert m.mrr == pytest.approx((1 + 1 / 2 + 1 / 6) / 4)
    assert compute_metrics([]).n == 0


def test_percentile_nearest_rank() -> None:
    values = list(range(1, 101))
    assert percentile(values, 95) == 95
    assert percentile([7], 95) == 7
    assert percentile([], 95) == 0.0


def _run(run_id: int, name: str, r1: float) -> EvalRun:
    return EvalRun(
        id=run_id,
        split="dev",
        dataset_version="synthetic_v1",
        config={"experiment": "E1", "name": name, "commit": "abc"},
        recall_at_1=r1,
        recall_at_5=r1,
        mrr=r1,
        p95_latency_ms=100,
        cost_per_query_usd=0.0,
    )


def test_latest_per_name_and_table() -> None:
    runs = [_run(1, "hybrid", 0.1), _run(3, "hybrid", 0.3), _run(2, "dense", 0.2)]
    latest = latest_per_name(runs)
    assert [(r.config or {})["name"] for r in latest] == ["dense", "hybrid"]
    assert [r.id for r in latest] == [2, 3]
    table = comparison_table(latest)
    assert "| hybrid | 0.300 |" in table and "| dense | 0.200 |" in table
    assert "| 0.300 | - | - |" in table  # 검색만 평가한 실행은 재질문 지표가 없다


def test_default_config_uses_env_weights() -> None:
    cfg = EvalConfig(experiment="E1", name="x")
    assert cfg.mode == "hybrid" and cfg.w_second_scene is None


def test_load_examples_image_skips_missing_file(tmp_path: Path) -> None:
    rows = [
        {
            "id": "img-1",
            "query": None,
            "image_path": "imgs/a.jpg",
            "answer_tmdb_id": 1,
            "split": "dev",
        },
        {
            "id": "img-2",
            "query": None,
            "image_path": "imgs/b.jpg",
            "answer_tmdb_id": 2,
            "split": "dev",
        },
    ]
    (tmp_path / "image_v1.jsonl").write_text(
        "".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8"
    )
    (tmp_path / "imgs").mkdir()
    (tmp_path / "imgs" / "a.jpg").write_bytes(b"x")
    examples = load_examples("dev", ["image"], tmp_path, repo_root=tmp_path)
    assert [(e.id, e.image_path) for e in examples] == [("img-1", "imgs/a.jpg")]
    assert examples[0].label == "[이미지 a.jpg]"


def test_img_caption_none_configs_load() -> None:
    for name in ("IMG_search_caption_none", "IMG_agent_caption_none"):
        cfg = load_config(CONFIGS / f"{name}.yaml")
        assert cfg.experiment == "IMG" and cfg.image_caption_reasoning_effort == "none"
    assert load_config(CONFIGS / "IMG_agent.yaml").image_caption_reasoning_effort is None
