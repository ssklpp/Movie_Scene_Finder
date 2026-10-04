import type { Step } from "../lib/api";

const LABELS: Record<Step, string> = {
  analyze: "사진 살펴보기",
  rewrite: "기억을 검색어로 정리하기",
  retrieve: "비슷한 장면 찾기",
  verify: "후보 영화 확인하기",
};

type Props = { steps: Step[]; done: Set<Step> };

/** 검색 단계. 실제로 순서대로 진행되므로 순서 목록으로 둔다. */
export default function Progress({ steps, done }: Props) {
  const current = steps.find((s) => !done.has(s));
  return (
    <ol className="mt-6 space-y-2" aria-label="검색 진행 상황">
      {steps.map((step) => {
        const finished = done.has(step);
        return (
          <li
            key={step}
            className={`flex items-center gap-3 ${finished || step === current ? "text-ink" : "text-muted"}`}
            aria-current={step === current ? "step" : undefined}
          >
            <span className="flex h-5 w-5 items-center justify-center rounded-full border border-line bg-white">
              {finished ? (
                <svg viewBox="0 0 12 12" className="h-3 w-3" aria-hidden>
                  <path
                    className="check-path"
                    d="M2 6.5 L5 9 L10 3"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="1.8"
                    strokeLinecap="round"
                  />
                </svg>
              ) : step === current ? (
                <span className="h-1.5 w-1.5 rounded-full bg-ink motion-safe:animate-pulse" />
              ) : null}
            </span>
            <span>{LABELS[step]}</span>
            <span className="sr-only">{finished ? "완료" : step === current ? "진행 중" : "대기"}</span>
          </li>
        );
      })}
    </ol>
  );
}
