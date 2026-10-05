"use client";

import { useEffect, useState } from "react";

import {
  EXPERIMENTS,
  METRICS,
  axisMax,
  fetchEvalRuns,
  groupRuns,
  type EvalRun,
  type Group,
  type Metric,
} from "../lib/evalRuns";

const SPLITS = [
  { key: "dev", label: "dev" },
  { key: "test", label: "test (최종)" },
];

type Load = { state: "loading" } | { state: "error" } | { state: "done"; runs: EvalRun[] };

export default function EvalDashboard() {
  const [load, setLoad] = useState<Load>({ state: "loading" });
  const [split, setSplit] = useState("dev");
  const [metricKey, setMetricKey] = useState(METRICS[0].key);

  useEffect(() => {
    fetchEvalRuns()
      .then((runs) => setLoad({ state: "done", runs }))
      .catch(() => setLoad({ state: "error" }));
  }, []);

  const metric = METRICS.find((m) => m.key === metricKey) ?? METRICS[0];

  return (
    <div className="mt-6">
      <p className="text-muted">
        실험 설정마다 가장 최근 실행을 보여 줍니다. 검색만 평가한 결과와 에이전트(재작성·검증·재질문)
        결과는 따로 묶었습니다. 재질문은 정답 영화 속성으로 답하는 시뮬레이터가 했습니다.
      </p>

      <div className="mt-6 flex flex-wrap gap-x-8 gap-y-3">
        <Segmented label="데이터" options={SPLITS} value={split} onChange={setSplit} />
        <Segmented
          label="지표"
          options={METRICS.map((m) => ({ key: m.key, label: m.label }))}
          value={metricKey}
          onChange={(k) => setMetricKey(k as Metric["key"])}
        />
      </div>

      {load.state === "loading" && <p className="mt-10 text-muted">평가 기록을 불러오는 중…</p>}
      {load.state === "error" && (
        <p className="mt-10" role="alert">
          평가 기록을 불러오지 못했어요. 검색 서버가 켜져 있는지 확인해 주세요.
        </p>
      )}
      {load.state === "done" && <Groups groups={groupRuns(load.runs, split)} metric={metric} />}
    </div>
  );
}

function Segmented({
  label,
  options,
  value,
  onChange,
}: {
  label: string;
  options: { key: string; label: string }[];
  value: string;
  onChange: (key: string) => void;
}) {
  return (
    <fieldset className="flex flex-wrap items-center gap-2">
      <legend className="sr-only">{label}</legend>
      <span aria-hidden className="mr-1 text-sm text-muted">
        {label}
      </span>
      {options.map((o) => (
        <button
          key={o.key}
          type="button"
          aria-pressed={o.key === value}
          onClick={() => onChange(o.key)}
          className={`rounded-full border px-3 py-1 text-sm transition-colors ${
            o.key === value
              ? "border-ink bg-ink text-paper"
              : "border-line text-ink hover:border-muted"
          }`}
        >
          {o.label}
        </button>
      ))}
    </fieldset>
  );
}

function Groups({ groups, metric }: { groups: Group[]; metric: Metric }) {
  if (!groups.length) {
    return <p className="mt-10 text-muted">이 데이터로 측정한 결과가 아직 없어요.</p>;
  }
  // 모든 실험이 같은 축을 써야 실험끼리 막대 길이를 비교할 수 있다.
  const max = axisMax(
    metric,
    groups.flatMap((g) => g.rows.map((r) => r.latest[metric.key])),
  );
  return (
    <div className="mt-8 space-y-12">
      {groups.map((g) => (
        <ExperimentSection key={groupId(g)} group={g} metric={metric} max={max} />
      ))}
    </div>
  );
}

function title(g: Group): string {
  const name = EXPERIMENTS[g.experiment];
  return `${g.experiment}${name ? ` ${name}` : ""}`;
}

// 표 열: 막대 지표 + 에이전트면 평균 재질문(MRR 다음)
const CLARIFY_COLUMN = {
  key: "avg_clarify",
  label: "평균 재질문",
  format: (v: number) => v.toFixed(2),
} as const;

function ExperimentSection({ group, metric, max }: { group: Group; metric: Metric; max: number }) {
  const columns = group.agent
    ? [...METRICS.slice(0, 3), CLARIFY_COLUMN, ...METRICS.slice(3)]
    : METRICS;
  return (
    <section aria-labelledby={groupId(group)}>
      <h2
        id={groupId(group)}
        className="flex flex-wrap items-baseline gap-x-3 font-display text-2xl"
      >
        {title(group)}
        <span className="font-sans text-sm text-muted">
          {group.agent ? "에이전트" : "검색만"} · {group.dataset || "데이터셋 미상"}
        </span>
      </h2>

      <ul className="mt-4 space-y-2" aria-label={`${metric.label} 막대 차트`}>
        {group.rows.map(({ latest: r }) => {
          const v = r[metric.key];
          const width = v === null ? 0 : Math.max((v / max) * 100, 0.5);
          return (
            <li
              key={r.id}
              className="group grid grid-cols-[minmax(0,7.5rem)_1fr] items-center gap-3 sm:grid-cols-[minmax(0,11rem)_1fr]"
            >
              <span className="truncate text-sm">{r.name}</span>
              {/* 값 글자 자리(5.5rem)를 뺀 트랙 안에서 막대 길이를 비례로 그리고, 값은 막대 끝에 둔다 */}
              <span className="relative h-6 pr-[5.5rem]">
                {v === null ? (
                  <span className="absolute inset-y-0 left-0 flex items-center text-sm text-muted">-</span>
                ) : (
                  <span className="relative block h-full">
                    <span
                      className="absolute inset-y-0.5 left-0 rounded-r bg-screen transition-[width] duration-300 group-hover:bg-ink motion-reduce:transition-none"
                      style={{ width: `${width}%` }}
                    />
                    <span
                      className="absolute inset-y-0 flex items-center pl-2 text-sm tabular-nums transition-[left] duration-300 motion-reduce:transition-none"
                      style={{ left: `${width}%` }}
                    >
                      {metric.format(v)}
                    </span>
                  </span>
                )}
              </span>
            </li>
          );
        })}
      </ul>

      <div className="mt-5 overflow-x-auto">
        <table className="w-full min-w-[40rem] border-y border-line text-sm tabular-nums">
          <caption className="sr-only">{title(group)} 전체 지표</caption>
          <thead className="text-left text-muted">
            <tr className="border-b border-line">
              <th scope="col" className="py-2 pr-3 font-normal">설정</th>
              {columns.map((c) => (
                <th key={c.key} scope="col" className="py-2 pr-3 text-right font-normal">
                  {c.label}
                </th>
              ))}
              <th scope="col" className="py-2 pr-3 text-right font-normal">실행</th>
              <th scope="col" className="py-2 font-normal">run</th>
            </tr>
          </thead>
          <tbody>
            {group.rows.map(({ latest: r, count }) => (
              <tr key={r.id} className="border-b border-line last:border-b-0">
                <th scope="row" className="py-2 pr-3 text-left font-medium">{r.name}</th>
                {columns.map((c) => {
                  const v = r[c.key];
                  return (
                    <td key={c.key} className="py-2 pr-3 text-right">
                      {v === null ? "-" : c.format(v)}
                    </td>
                  );
                })}
                <td className="py-2 pr-3 text-right">{count}회</td>
                <td className="py-2 text-muted">#{r.id}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function groupId(g: Group): string {
  return `exp-${g.experiment}-${g.dataset}-${g.agent}`.replace(/[^\w-]/g, "_");
}
