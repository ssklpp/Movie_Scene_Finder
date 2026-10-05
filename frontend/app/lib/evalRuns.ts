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
  avg_clarify: number | null;
  p95_latency_ms: number | null;
  cost_per_query_usd: number | null;
  commit: string | null;
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

/** 실험(SPEC §11)의 이름, 결론, 운영에 쓰는 설정 이름. 결론은 CLAUDE.md의 실험 기록과 같다. */
export type Experiment = { title: string; decision?: string; chosen?: string[] };

export const EXPERIMENTS: Record<string, Experiment> = {
  E1: {
    title: "검색 방식",
    decision: "하이브리드(dense + BM25)가 dense만 쓸 때보다 첫 번째 적중이 두 배라 하이브리드로 검색한다.",
    chosen: ["hybrid"],
  },
  E2: { title: "캡션 모델" },
  E3: {
    title: "검색 문서 언어",
    decision: "장면 문서에 한국어와 영어 캡션을 함께 넣었다. 검색만 했을 때 첫 번째 적중이 0.205에서 0.255로 올랐다.",
    chosen: ["caption_both", "caption_both_agent"],
  },
  E4: {
    title: "토크나이저",
    decision: "합성 질의에는 제목·인물 이름이 없어 사용자 사전의 효과가 없지만, 사람이 쓴 질의를 위해 유지한다.",
    chosen: ["kiwi_dict"],
  },
  E5: {
    title: "줄거리 가중치 W_PLOT",
    decision: "0이 조금 낫지만 흔들림 범위다. 사진에 없는 장면은 줄거리로만 찾을 수 있어 0.5를 유지한다.",
    chosen: ["wplot_0.5", "wplot_0.5_agent"],
  },
  E6: {
    title: "최대 재질문 횟수",
    decision: "재질문은 2회까지. 재작성·검증의 추론을 꺼도 정확도는 같고 오래 걸리는 요청이 사라졌다.",
    chosen: ["turns2_all_none"],
  },
  E7: {
    title: "임베딩 차원",
    decision: "512차원은 상위 5위 적중이 4.5%p 낮아 1536차원을 유지한다.",
    chosen: ["dim_1536"],
  },
  IMG: {
    title: "이미지 질의",
    decision:
      "사진만 있는 질의는 재작성 없이 캡션으로 바로 검색한다. 정확도는 같고 요청이 약 2.5초 빨라졌다. 캡션 추론은 끄면 정확도가 조금 낮아 유지한다.",
    chosen: ["search_hybrid", "agent_turns2_skip_rewrite"],
  },
  FINAL: {
    title: "최종 측정",
    decision: "설정을 모두 정한 뒤 test 세트로 한 번만 잰 결과다. 검색만(search)은 같은 질의의 기준선이다.",
    chosen: ["agent"],
  },
};

/** 화면에 보일 데이터셋 이름 */
export const DATASETS: Record<string, string> = {
  synthetic_v1: "합성 기억 묘사",
  human_v1: "사람이 쓴 묘사",
  image_v1: "사진",
};

type HeadlineRun = { experiment: string; name: string; dataset?: string; label: string };

/**
 * 맨 위 자막에 쓰는 운영 설정 실행. dev는 설정을 고른 실험의 운영 설정(텍스트·사진 에이전트),
 * test는 최종 측정(FINAL)의 사람이 쓴 묘사(MVP 목표의 기준)와 사진이다.
 */
const HEADLINE: Record<string, HeadlineRun[]> = {
  dev: [
    { experiment: "E3", name: "caption_both_agent", label: "기억 묘사" },
    { experiment: "IMG", name: "agent_turns2_skip_rewrite", label: "사진" },
  ],
  test: [
    { experiment: "FINAL", name: "agent", dataset: "human_v1", label: "사람이 쓴 묘사" },
    { experiment: "FINAL", name: "agent", dataset: "image_v1", label: "사진" },
  ],
};

/** split의 운영 설정 결과(설정마다 최신 실행). 없는 것은 빠진다. */
export function headline(runs: EvalRun[], split: string): { label: string; run: EvalRun }[] {
  return (HEADLINE[split] ?? []).flatMap(({ experiment, name, dataset, label }) => {
    const matches = runs.filter(
      (r) =>
        r.split === split &&
        r.experiment === experiment &&
        r.name === name &&
        (dataset === undefined || r.dataset_version === dataset),
    );
    if (!matches.length) return [];
    return [{ label, run: matches.reduce((a, b) => (b.id > a.id ? b : a)) }];
  });
}

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
