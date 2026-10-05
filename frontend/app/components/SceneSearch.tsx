"use client";

import { useState } from "react";

import {
  ApiError,
  type Question,
  type ResultItem,
  type SearchEvent,
  type Step,
  answer,
  search,
} from "../lib/api";
import Progress from "./Progress";
import QuestionCard from "./QuestionCard";
import Results from "./Results";
import SceneFrame from "./SceneFrame";

const EXAMPLES = [
  "기차 안에서 사람들이 좀비를 피해 칸 사이 문을 막고 버티던 장면",
  "초록색 괴물이 숲속 오두막 문을 열고 나오던 영화",
  "할아버지가 풍선을 잔뜩 매단 집을 타고 하늘로 날아가던 장면",
];

type Phase = "idle" | "running" | "question" | "done" | "error";

export default function SceneSearch() {
  const [text, setText] = useState("");
  const [image, setImage] = useState<File | null>(null);
  const [phase, setPhase] = useState<Phase>("idle");
  const [steps, setSteps] = useState<Step[]>([]);
  const [done, setDone] = useState<Set<Step>>(new Set());
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [question, setQuestion] = useState<Question | null>(null);
  const [result, setResult] = useState<{ items: ResultItem[]; confidence: number } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [submittedText, setSubmittedText] = useState("");

  const busy = phase === "running";

  async function consume(events: AsyncGenerator<SearchEvent>) {
    setPhase("running");
    setError(null);
    try {
      for await (const e of events) {
        if (e.event === "session") setSessionId(e.data.session_id);
        else if (e.event === "status") setDone((d) => new Set(d).add(e.data.step));
        else if (e.event === "question") {
          setQuestion(e.data);
          setPhase("question");
        } else if (e.event === "result") {
          setResult(e.data);
          setPhase("done");
        } else if (e.event === "error") {
          setError(
            e.data.code === "timeout"
              ? "찾는 데 너무 오래 걸렸어요. 다시 찾아 주세요."
              : e.data.code === "image_unreadable"
                ? e.data.message
                : "검색 중에 문제가 생겼어요. 다시 찾아 주세요.",
          );
          setPhase("error");
        }
      }
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "검색 서버에 연결하지 못했어요.");
      setPhase("error");
    }
  }

  function start() {
    if (busy || (!text.trim() && !image)) return;
    setSteps(image ? ["analyze", "rewrite", "retrieve", "verify"] : ["rewrite", "retrieve", "verify"]);
    setDone(new Set());
    setQuestion(null);
    setResult(null);
    setSessionId(null);
    setSubmittedText(text);
    void consume(search(text, image));
  }

  function reply(value: string) {
    if (!sessionId) return;
    setQuestion(null);
    // 답을 받으면 검색과 확인을 다시 한다
    setSteps((s) => [...s.filter((x) => x !== "retrieve" && x !== "verify"), "retrieve", "verify"]);
    setDone((d) => {
      const next = new Set(d);
      next.delete("retrieve");
      next.delete("verify");
      return next;
    });
    void consume(answer(sessionId, value));
  }

  return (
    <>
      <h1 className="mt-10 max-w-2xl font-display text-4xl leading-tight sm:text-5xl">
        제목은 몰라도 장면은 기억나죠
      </h1>
      <p className="mt-3 max-w-xl text-muted">
        떠오르는 장면을 자막처럼 적어 주세요. 흐릿해도 괜찮아요. 영화 300편 중에서 찾아 드릴게요.
      </p>

      <form
        className="mt-8"
        onSubmit={(e) => {
          e.preventDefault();
          start();
        }}
      >
        <SceneFrame
          text={text}
          onTextChange={setText}
          image={image}
          onImageChange={setImage}
          onSubmit={start}
          onImageError={(m) => {
            setError(m);
            setPhase("error");
          }}
          disabled={busy}
        />
        <div className="mt-4 flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
          <div className="flex flex-wrap gap-2" aria-label="예시 장면">
            {EXAMPLES.map((ex) => (
              <button
                key={ex}
                type="button"
                disabled={busy}
                onClick={() => setText(ex)}
                className="max-w-full truncate rounded-sm border border-line bg-white/60 px-3 py-1.5 text-left text-sm text-muted hover:border-ink hover:text-ink disabled:opacity-50"
              >
                {ex}
              </button>
            ))}
          </div>
          <button
            type="submit"
            disabled={busy || (!text.trim() && !image)}
            className="shrink-0 rounded-sm bg-ink px-6 py-3 font-medium text-white hover:bg-screen disabled:cursor-not-allowed disabled:opacity-40"
          >
            {busy ? "찾는 중" : "영화 찾기"}
          </button>
        </div>
      </form>

      {error && (
        <p role="alert" className="mt-6 border-l-4 border-ink bg-white px-4 py-3">
          {error}
        </p>
      )}

      {(busy || phase === "question") && <Progress steps={steps} done={done} />}

      {phase === "question" && question && (
        <QuestionCard question={question} onAnswer={reply} disabled={busy} />
      )}

      {phase === "done" && result && sessionId && (
        <Results
          sessionId={sessionId}
          items={result.items}
          confidence={result.confidence}
          query={submittedText}
        />
      )}
    </>
  );
}
