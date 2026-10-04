// 검색 API(SPEC §9) 클라이언트. 응답은 POST에 대한 SSE 스트림이라 EventSource 대신 fetch로 읽는다.

export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export type Step = "analyze" | "rewrite" | "retrieve" | "verify";

export type Evidence = {
  scene_id: string;
  thumb_url: string | null;
  caption_ko: string;
};

export type ResultItem = {
  movie_id: number;
  title_ko: string | null;
  year: number | null;
  poster_url: string | null;
  score: number;
  reason: string;
  evidence: Evidence[];
};

export type Question = {
  text: string;
  attr: string;
  options: string[];
  labels: string[];
};

export type SearchEvent =
  | { event: "session"; data: { session_id: string } }
  | { event: "status"; data: { step: Step; message: string } }
  | { event: "question"; data: Question }
  | { event: "result"; data: { items: ResultItem[]; confidence: number } }
  | { event: "error"; data: { code: string; message: string } };

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

// 상태 코드별로 사용자가 할 수 있는 일을 알려준다.
function errorMessage(status: number, detail: string): string {
  if (status === 429) return "오늘 검색할 수 있는 횟수를 다 썼어요. 내일 다시 찾아 주세요.";
  if (status === 413) return "사진은 5MB 이하만 올릴 수 있어요.";
  if (status === 409) return "이 검색은 이미 끝났어요. 새로 검색해 주세요.";
  if (status === 400) return detail.includes("JPEG")
    ? "사진은 JPEG이나 PNG만 올릴 수 있어요."
    : "장면 설명이나 사진 중 하나는 있어야 해요.";
  return "검색 서버에 연결하지 못했어요. 잠시 뒤 다시 시도해 주세요.";
}

/** SSE 본문을 이벤트 단위로 나눈다. 블록 사이는 빈 줄이고 줄바꿈은 \r\n일 수 있다. */
export function parseBlocks(buffer: string): { events: SearchEvent[]; rest: string } {
  const blocks = buffer.split(/\r?\n\r?\n/);
  const rest = blocks.pop() ?? "";
  const events: SearchEvent[] = [];
  for (const block of blocks) {
    let name = "";
    const data: string[] = [];
    for (const line of block.split(/\r?\n/)) {
      if (line.startsWith("event:")) name = line.slice(6).trim();
      else if (line.startsWith("data:")) data.push(line.slice(5).trim());
    }
    if (name && data.length) {
      events.push({ event: name, data: JSON.parse(data.join("\n")) } as SearchEvent);
    }
  }
  return { events, rest };
}

async function* stream(res: Response): AsyncGenerator<SearchEvent> {
  if (!res.ok || !res.body) {
    let detail = "";
    try {
      detail = String((await res.json()).detail ?? "");
    } catch {
      // 본문이 JSON이 아니면 상태 코드로만 안내한다
    }
    throw new ApiError(res.status, errorMessage(res.status, detail));
  }
  const reader = res.body.pipeThrough(new TextDecoderStream()).getReader();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    const parsed = parseBlocks(buffer + value);
    buffer = parsed.rest;
    yield* parsed.events;
  }
}

async function post(path: string, init: RequestInit): Promise<Response> {
  try {
    return await fetch(`${API_URL}${path}`, { method: "POST", ...init });
  } catch {
    throw new ApiError(0, errorMessage(0, ""));
  }
}

export async function* search(text: string, image: File | null): AsyncGenerator<SearchEvent> {
  const form = new FormData();
  if (text.trim()) form.append("text", text.trim());
  if (image) form.append("image", image);
  yield* stream(await post("/search", { body: form }));
}

export async function* answer(sessionId: string, value: string): AsyncGenerator<SearchEvent> {
  const res = await post(`/search/${sessionId}/answer`, {
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ value }),
  });
  yield* stream(res);
}

export async function sendFeedback(sessionId: string, movieId: number, isCorrect: boolean) {
  const res = await post("/feedback", {
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session_id: sessionId, movie_id: movieId, is_correct: isCorrect }),
  });
  if (!res.ok) throw new ApiError(res.status, errorMessage(res.status, ""));
}
