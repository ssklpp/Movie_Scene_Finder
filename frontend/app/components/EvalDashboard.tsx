"use client";

import { useEffect, useState } from "react";

import {
  DATASETS,
  EXPERIMENTS,
  METRICS,
  axisMax,
  fetchEvalRuns,
  groupRuns,
  headline,
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
  const hasResult = load.state === "done" && headline(load.runs, split).length > 0;

  return (
    <div className="mt-6">
      <Screen load={load} split={split} />
      {hasResult && (
        <p className="mt-3 max-w-[65ch] text-sm leading-relaxed text-muted">
          {split} 세트에서 지금 서비스에 쓰는 설정(질의 재작성, 검색, 검증, 재질문 최대 2회)으로 잰
          결과입니다. 재질문에는 정답 영화의 속성으로 답하는 시뮬레이터가 답했습니다.
        </p>
      )}

      <div className="mt-10 flex flex-wrap gap-x-8 gap-y-3">
        <Segmented label="데이터" options={SPLITS} value={split} onChange={setSplit} />
        <Segmented
          label="지표"
          options={METRICS.map((m) => ({ key: m.key, label: m.label }))}
          value={metricKey}
          onChange={(k) => setMetricKey(k as Metric["key"])}
        />
      </div>

      {load.state === "done" && (
        <Experiments groups={groupRuns(load.runs, split)} metric={metric} split={split} />
      )}
    </div>
  );
}

/** 검색 화면과 같은 영화 화면. 운영 설정의 결과를 자막 한 줄로 보여 준다. */
function Screen({ load, split }: { load: Load; split: string }) {
  let subtitle: string | null = null;
  let note: string;
  if (load.state === "loading") {
    note = "평가 기록을 불러오는 중…";
  } else if (load.state === "error") {
    note = "평가 기록을 불러오지 못했어요. 검색 서버가 켜져 있는지 확인해 주세요.";
  } else {
    const found = headline(load.runs, split).filter(({ run }) => run.recall_at_1 !== null);
    const parts = found.map(({ label, run }) => `${label}의 ${Math.round(run.recall_at_1! * 100)}%`);
    // "88%"와 "에서" 사이에서 줄이 끊기지 않도록 단어 결합 문자(U+2060)를 넣는다.
    subtitle = parts.length
      ? `${parts.join(", ")}⁠에서 찾던 영화를 첫 번째로 보여 줬어요`
      : null;
    note = `아직 ${split} 세트로 잰 결과가 없어요.`;
  }
  return (
    <div
      className="relative flex min-h-48 items-end justify-center overflow-hidden rounded-sm border-[6px] border-screen-edge bg-screen px-6 pb-6 sm:aspect-[2.39/1] sm:px-16"
      role={load.state === "error" ? "alert" : undefined}
      aria-live="polite"
    >
      {subtitle ? (
        <p className="subtitle-text text-balance text-center text-xl font-medium leading-snug sm:text-3xl">
          {subtitle}
        </p>
      ) : (
        <p className="text-center text-sm text-white/60">{note}</p>
      )}
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

/** 실험마다 결론 한 줄과, 평가 방식·데이터셋별 막대·표 */
function Experiments({ groups, metric, split }: { groups: Group[]; metric: Metric; split: string }) {
  if (!groups.length) {
    return (
      <p className="mt-10 max-w-[60ch] leading-relaxed text-muted">
        {split === "test"
          ? "test 세트는 설정을 모두 정한 뒤 최종 측정에 한 번만 씁니다. 측정하면 여기에 데이터셋별 결과가 나와요."
          : `${split} 세트로 돌린 평가가 없어요. eval.run_eval로 평가를 돌리면 여기에 나와요.`}
      </p>
    );
  }
  // 모든 실험이 같은 축을 써야 실험끼리 막대 길이를 비교할 수 있다.
  const max = axisMax(
    metric,
    groups.flatMap((g) => g.rows.map((r) => r.latest[metric.key])),
  );
  const byExperiment = new Map<string, Group[]>();
  for (const g of groups) byExperiment.set(g.experiment, [...(byExperiment.get(g.experiment) ?? []), g]);
  return (
    <div className="mt-10 divide-y divide-line border-t border-line">
      {[...byExperiment].map(([experiment, subgroups]) => {
        const info = EXPERIMENTS[experiment];
        return (
          <section key={experiment} aria-labelledby={`exp-${experiment}`} className="py-10">
            <h2 id={`exp-${experiment}`} className="font-display text-2xl">
              {experiment}
              {info && ` ${info.title}`}
            </h2>
            {info?.decision && <p className="mt-2 max-w-[60ch] leading-relaxed">{info.decision}</p>}
            {subgroups.map((g) => (
              <Subgroup key={groupId(g)} group={g} metric={metric} max={max} chosen={info?.chosen ?? []} />
            ))}
          </section>
        );
      })}
    </div>
  );
}

// 표 열: 막대 지표 + 에이전트면 평균 재질문(MRR 다음)
const CLARIFY_COLUMN = {
  key: "avg_clarify",
  label: "평균 재질문",
  format: (v: number) => v.toFixed(2),
} as const;

function Subgroup({
  group,
  metric,
  max,
  chosen,
}: {
  group: Group;
  metric: Metric;
  max: number;
  chosen: string[];
}) {
  const columns = group.agent
    ? [...METRICS.slice(0, 3), CLARIFY_COLUMN, ...METRICS.slice(3)]
    : METRICS;
  const caption = `${group.agent ? "에이전트" : "검색만"}, ${DATASETS[group.dataset] ?? (group.dataset || "데이터셋 미상")}`;
  return (
    <div className="mt-6" aria-labelledby={groupId(group)} role="group">
      <h3 id={groupId(group)} className="text-sm text-muted">
        {caption}
      </h3>

      <ul className="mt-3 space-y-2" aria-label={`${metric.label} 막대 차트`}>
        {group.rows.map(({ latest: r }) => {
          const v = r[metric.key];
          const width = v === null ? 0 : Math.max((v / max) * 100, 0.5);
          const isChosen = chosen.includes(r.name);
          return (
            <li
              key={r.id}
              className="grid grid-cols-[minmax(0,8.5rem)_1fr] items-center gap-3 sm:grid-cols-[minmax(0,13rem)_1fr]"
            >
              <span className="flex min-w-0 items-baseline gap-2 text-sm">
                <span className={`truncate ${isChosen ? "font-semibold" : ""}`}>{r.name}</span>
                {isChosen && <span className="shrink-0 text-xs text-muted">운영</span>}
              </span>
              {/* 값 글자 자리(5.5rem)를 뺀 트랙 안에서 막대 길이를 비례로 그리고, 값은 막대 끝에 둔다 */}
              <span className="relative h-6 pr-[5.5rem]">
                {v === null ? (
                  <span className="absolute inset-y-0 left-0 flex items-center text-sm text-muted">-</span>
                ) : (
                  <span className="relative block h-full">
                    <span
                      className={`absolute inset-y-0.5 left-0 rounded-r transition-[width] duration-300 motion-reduce:transition-none ${
                        isChosen ? "bg-ink" : "bg-muted"
                      }`}
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

      <details className="mt-3">
        <summary className="cursor-pointer text-sm text-muted hover:text-ink">전체 지표 보기</summary>
        <div className="mt-2 overflow-x-auto">
          <table className="w-full min-w-[40rem] border-y border-line text-sm tabular-nums">
            <caption className="sr-only">{caption} 전체 지표</caption>
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
      </details>
    </div>
  );
}

function groupId(g: Group): string {
  return `exp-${g.experiment}-${g.dataset}-${g.agent}`.replace(/[^\w-]/g, "_");
}
