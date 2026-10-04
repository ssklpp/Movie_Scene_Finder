import type { Question } from "../lib/api";

type Props = { question: Question; onAnswer: (value: string) => void; disabled: boolean };

/** 재질문(SPEC §10). 선택지는 버튼이고 "모르겠어요"는 마지막에 덜 눈에 띄게 둔다. */
export default function QuestionCard({ question, onAnswer, disabled }: Props) {
  const unknownIndex = question.options.indexOf("unknown");
  return (
    <section className="mt-8 border-l-4 border-screen bg-white px-5 py-5" aria-live="polite">
      <h2 className="text-lg font-medium">{question.text}</h2>
      <p className="mt-1 text-sm text-muted">하나만 알려 주셔도 후보를 좁힐 수 있어요.</p>
      <div className="mt-4 flex flex-wrap gap-2">
        {question.options.map((value, i) => (
          <button
            key={value}
            type="button"
            disabled={disabled}
            onClick={() => onAnswer(value)}
            className={
              i === unknownIndex
                ? "rounded-sm px-4 py-2 text-muted underline-offset-4 hover:underline disabled:opacity-50"
                : "rounded-sm bg-screen px-4 py-2 text-white hover:bg-ink disabled:opacity-50"
            }
          >
            {question.labels[i] ?? value}
          </button>
        ))}
      </div>
    </section>
  );
}
