import { describe, expect, it } from "vitest";

import { parseBlocks } from "./api";

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
