import { describe, expect, it } from "vitest";

import { METRICS, axisMax, formatUsd, groupRuns, type EvalRun } from "./evalRuns";

function run(id: number, experiment: string, name: string, extra: Partial<EvalRun> = {}): EvalRun {
  return {
    id,
    experiment,
    name,
    split: "dev",
    dataset_version: "synthetic_v1",
    agent: false,
    recall_at_1: 0.2,
    recall_at_5: 0.4,
    mrr: 0.3,
    clarify_success: null,
    avg_clarify: null,
    p95_latency_ms: 100,
    cost_per_query_usd: 0,
    commit: "abc",
    created_at: "2026-10-05T00:00:00Z",
    ...extra,
  };
}

describe("groupRuns", () => {
  it("keeps the latest run per name and counts repeats", () => {
    const groups = groupRuns(
      [run(3, "E1", "hybrid"), run(1, "E1", "hybrid"), run(2, "E1", "dense")],
      "dev",
    );
    expect(groups).toHaveLength(1);
    expect(groups[0].rows.map((r) => [r.latest.name, r.latest.id, r.count])).toEqual([
      ["dense", 2, 1],
      ["hybrid", 3, 2],
    ]);
  });

  it("separates search-only and agent runs, filters split, orders E2 before E10", () => {
    const groups = groupRuns(
      [
        run(1, "E10", "x"),
        run(2, "E3", "ko_agent", { agent: true }),
        run(3, "E3", "ko"),
        run(4, "E1", "hybrid", { split: "test" }),
      ],
      "dev",
    );
    expect(groups.map((g) => [g.experiment, g.agent])).toEqual([
      ["E3", false],
      ["E3", true],
      ["E10", false],
    ]);
  });
});

describe("axisMax", () => {
  const recall = METRICS.find((m) => m.key === "recall_at_1")!;
  const p95 = METRICS.find((m) => m.key === "p95_latency_ms")!;

  it("fixes ratio metrics to 1 and scales others to the largest value", () => {
    expect(axisMax(recall, [0.2, 0.5])).toBe(1);
    expect(axisMax(p95, [3000, null, 8000])).toBe(8000);
    expect(axisMax(p95, [null])).toBe(1);
  });
});

describe("formatUsd", () => {
  it("keeps two significant digits for tiny costs", () => {
    expect(formatUsd(1.2393e-6)).toBe("$0.0000012");
    expect(formatUsd(0.00062)).toBe("$0.00062");
    expect(formatUsd(0)).toBe("$0");
  });
});
