import { afterEach, describe, expect, it, vi } from "vitest";

import { parseBlocks, post } from "./api";

describe("parseBlocks", () => {
  it("splits SSE blocks and keeps an unfinished block for the next chunk", () => {
    const body =
      'event: session\r\ndata: {"session_id": "s1"}\r\n\r\n' +
      'event: status\r\ndata: {"step": "rewrite", "message": "정리했어요"}\r\n\r\n' +
      "event: result\r\ndata: {\"items\":";
    const { events, rest } = parseBlocks(body);
    expect(events).toEqual([
      { event: "session", data: { session_id: "s1" } },
      { event: "status", data: { step: "rewrite", message: "정리했어요" } },
    ]);
    expect(rest).toBe('event: result\r\ndata: {"items":');

    const next = parseBlocks(rest + ' [], "confidence": 0.8}\n\n');
    expect(next.events).toEqual([{ event: "result", data: { items: [], confidence: 0.8 } }]);
    expect(next.rest).toBe("");
  });

  it("ignores comments and blocks without event or data", () => {
    const { events } = parseBlocks(": ping\n\nevent: status\n\ndata: {}\n\n");
    expect(events).toEqual([]);
  });
});

describe("post", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.useRealTimers();
  });

  it("retries while the platform proxy answers 502 (server waking up)", async () => {
    vi.useFakeTimers();
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(new Response("", { status: 502 }))
      .mockResolvedValueOnce(new Response("", { status: 503 }))
      .mockResolvedValueOnce(new Response("ok", { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);

    const pending = post("/search", { body: "x" });
    await vi.runAllTimersAsync();
    const res = await pending;

    expect(res.status).toBe(200);
    expect(fetchMock).toHaveBeenCalledTimes(3);
  });

  it("does not retry app errors such as rate limit", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response("", { status: 429 }));
    vi.stubGlobal("fetch", fetchMock);

    const res = await post("/search", { body: "x" });

    expect(res.status).toBe(429);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});
