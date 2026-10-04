"use client";

import Image from "next/image";
import { useState } from "react";

import { type ResultItem, sendFeedback } from "../lib/api";
import { highlight, queryTerms } from "../lib/highlight";

// 백엔드 재질문 기준(CONFIDENCE_THRESHOLD)과 같다. 이보다 낮으면 결과가 확실하지 않다고 알린다.
const CONFIDENT = 0.7;

type Props = {
  sessionId: string;
  items: ResultItem[];
  confidence: number;
  query: string;
};

type Vote = "correct" | "wrong" | "failed";

export default function Results({ sessionId, items, confidence, query }: Props) {
  const terms = queryTerms(query);
  const [votes, setVotes] = useState<Record<number, Vote>>({});

  async function vote(movieId: number, isCorrect: boolean) {
    setVotes((v) => ({ ...v, [movieId]: isCorrect ? "correct" : "wrong" }));
    try {
      await sendFeedback(sessionId, movieId, isCorrect);
    } catch {
      setVotes((v) => ({ ...v, [movieId]: "failed" }));
    }
  }

  if (!items.length) {
    return (
      <section className="mt-10" aria-live="polite">
        <h2 className="font-display text-3xl">맞는 영화를 찾지 못했어요</h2>
        <p className="mt-2 text-muted">
          장소나 인물의 생김새, 눈에 띄던 물건을 더 적어서 다시 찾아 보세요.
        </p>
      </section>
    );
  }

  return (
    <section className="mt-10" aria-live="polite">
      <h2 className="font-display text-3xl">이 영화들일 수 있어요</h2>
      {confidence < CONFIDENT && (
        <p className="mt-2 text-muted">
          확실하지 않아요. 아래 후보에 없다면 장면을 조금 더 자세히 적어 다시 찾아 보세요.
        </p>
      )}
      <ol className="mt-6 divide-y divide-line border-y border-line">
        {items.map((item, i) => (
          <li key={item.movie_id} className="grid grid-cols-[2rem_4.5rem_1fr] gap-4 py-5 sm:grid-cols-[2.5rem_6rem_1fr]">
            <span className="font-display text-3xl leading-none text-muted" aria-label={`${i + 1}위`}>
              {i + 1}
            </span>
            {item.poster_url ? (
              <Image
                src={item.poster_url}
                alt={`${item.title_ko ?? "영화"} 포스터`}
                width={96}
                height={144}
                className="h-auto w-full rounded-sm"
              />
            ) : (
              <div className="aspect-[2/3] w-full rounded-sm bg-line" />
            )}
            <div className="min-w-0">
              <h3 className="text-xl font-semibold">
                {item.title_ko ?? "제목 미상"}
                {item.year && <span className="ml-2 text-base font-normal text-muted">{item.year}</span>}
              </h3>
              {item.reason && <p className="mt-1 leading-relaxed">{item.reason}</p>}
              {!item.reason && item.evidence.length === 0 && (
                // 장면이 아니라 줄거리 검색으로만 올라온 후보
                <p className="mt-1 text-muted">줄거리가 비슷해 후보에 올랐어요.</p>
              )}
              {item.evidence.length > 0 && (
                <ul className="mt-3 space-y-2 text-sm text-muted">
                  {item.evidence.map((e) => (
                    <li key={e.scene_id} className="flex items-start gap-3 border-l-2 border-line pl-3">
                      {e.thumb_url && (
                        // eslint-disable-next-line @next/next/no-img-element -- R2 썸네일은 이미 512px로 줄여 올렸다
                        <img
                          src={e.thumb_url}
                          alt=""
                          loading="lazy"
                          width={512}
                          height={288}
                          className="aspect-video w-24 shrink-0 rounded-sm bg-line object-cover sm:w-32"
                          onError={(ev) => (ev.currentTarget.style.display = "none")}
                        />
                      )}
                      <p className="min-w-0">
                        {highlight(e.caption_ko, terms).map((seg, k) =>
                          seg.match ? (
                            <mark key={k} className="bg-subtitle/60 px-0.5 text-ink">
                              {seg.text}
                            </mark>
                          ) : (
                            <span key={k}>{seg.text}</span>
                          ),
                        )}
                      </p>
                    </li>
                  ))}
                </ul>
              )}
              <div className="mt-3 flex items-center gap-3 text-sm">
                {votes[item.movie_id] === "correct" || votes[item.movie_id] === "wrong" ? (
                  <p className="text-muted">알려 주셔서 고마워요. 다음 검색에 반영할게요.</p>
                ) : (
                  <>
                    <span className="text-muted">이 영화가 맞나요?</span>
                    <button
                      type="button"
                      onClick={() => vote(item.movie_id, true)}
                      className="rounded-sm border border-ink px-3 py-1 hover:bg-ink hover:text-white"
                    >
                      맞아요
                    </button>
                    <button
                      type="button"
                      onClick={() => vote(item.movie_id, false)}
                      className="rounded-sm border border-line px-3 py-1 text-muted hover:border-ink hover:text-ink"
                    >
                      아니에요
                    </button>
                    {votes[item.movie_id] === "failed" && (
                      <span className="text-muted">전송하지 못했어요. 다시 눌러 주세요.</span>
                    )}
                  </>
                )}
              </div>
            </div>
          </li>
        ))}
      </ol>
    </section>
  );
}
