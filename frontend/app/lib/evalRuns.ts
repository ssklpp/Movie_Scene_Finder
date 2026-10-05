// 내부 평가 대시보드(SPEC §10 /eval)가 읽는 eval_runs. GET /eval/runs 응답과 같은 모양이다.

import { API_URL } from "./api";

export type EvalRun = {
  id: number;
  experiment: string;
  name: string;
  split: string;
  dataset_version: string | null;
  agent: boolean;
  recall_at_1: number | null;
  recall_at_5: number | null;
  mrr: number | null;
  clarify_success: number | null;
  avg_clarify: number | null;
  p95_latency_ms: number | null;
  cost_per_query_usd: number | null;
  commit: string | null;
  created_at: string;
};

export type MetricKey = "recall_at_1" | "recall_at_5" | "mrr" | "p95_latency_ms" | "cost_per_query_usd";

export type Metric = {
  key: MetricKey;
  label: string;
  // 막대 축의 최댓값. 비율 지표는 0~1로 고정해 실험끼리 길이를 비교할 수 있게 한다.
  fixedMax?: number;
  format: (v: number) => string;
};

export const METRICS: Metric[] = [
  { key: "recall_at_1", label: "Recall@1", fixedMax: 1, format: (v) => v.toFixed(3) },
  { key: "recall_at_5", label: "Recall@5", fixedMax: 1, format: (v) => v.toFixed(3) },
  { key: "mrr", label: "MRR", fixedMax: 1, format: (v) => v.toFixed(3) },
  { key: "p95_latency_ms", label: "p95 지연", format: (v) => `${(v / 1000).toFixed(1)}초` },
  { key: "cost_per_query_usd", label: "질의당 비용", format: formatUsd },
];

// SPEC §11 실험 설정 표
export const EXPERIMENTS: Record<string, string> = {
  E1: "검색 방식",
  E2: "캡션 모델",
  E3: "검색 문서 언어",
  E4: "토크나이저",
  E5: "줄거리 가중치 W_PLOT",
  E6: "최대 재질문 횟수",
  E7: "임베딩 차원",
  IMG: "이미지 질의",
};

/** 같은 실험·split·데이터셋·평가 방식(검색만/에이전트)의 설정별 최신 실행과 실행 횟수. */
export type Group = {
  experiment: string;
  dataset: string;
  agent: boolean;
  rows: { latest: EvalRun; count: number }[];
};

/**
 * split 하나의 실행을 실험·데이터셋·평가 방식별로 묶고, 설정 이름마다 가장 최근(id가 큰) 실행만
 * 남긴다. 같은 설정을 다른 데이터셋(예: test의 synthetic과 human)으로 돌린 결과가 서로 덮지 않는다.
 */
export function groupRuns(runs: EvalRun[], split: string): Group[] {
  const groups = new Map<string, Group>();
  for (const run of runs) {
    if (run.split !== split) continue;
    const dataset = run.dataset_version ?? "";
    const gkey = `${run.experiment}|${dataset}|${run.agent}`;
    const group = groups.get(gkey) ?? { experiment: run.experiment, dataset, agent: run.agent, rows: [] };
    groups.set(gkey, group);
    const prev = group.rows.find((r) => r.latest.name === run.name);
    if (prev) {
      if (run.id > prev.latest.id) prev.latest = run;
      prev.count += 1;
    } else {
      group.rows.push({ latest: run, count: 1 });
    }
  }
  for (const g of groups.values()) {
    g.rows.sort((a, b) => a.latest.name.localeCompare(b.latest.name));
  }
  return [...groups.values()].sort(
    (a, b) =>
      a.experiment.localeCompare(b.experiment, undefined, { numeric: true }) ||
      a.dataset.localeCompare(b.dataset) ||
      Number(a.agent) - Number(b.agent),
  );
}

/** 막대 축 최댓값: 고정값이 없으면 주어진 값 중 가장 큰 값(대시보드는 모든 실험 값을 준다). */
export function axisMax(metric: Metric, values: (number | null)[]): number {
  if (metric.fixedMax !== undefined) return metric.fixedMax;
  return Math.max(0, ...values.filter((v): v is number => v !== null)) || 1;
}

export async function fetchEvalRuns(): Promise<EvalRun[]> {
  const res = await fetch(`${API_URL}/eval/runs`);
  if (!res.ok) throw new Error(`eval runs: ${res.status}`);
  return res.json();
}

/** 질의당 비용은 검색만이면 $0.000001 수준이라 자릿수 대신 유효숫자 2자리로 쓴다. */
export function formatUsd(v: number): string {
  return v === 0 ? "$0" : `$${Number(v.toPrecision(2))}`;
}
