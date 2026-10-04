import { describe, expect, it } from "vitest";

import { highlight, queryTerms } from "./highlight";

describe("queryTerms", () => {
  it("strips particles and drops short or common words", () => {
    expect(queryTerms("기차 안에서 사람들이 좀비를 피해 문을 막고 버티던 장면")).toEqual([
      "기차",
      "사람들",
      "좀비",
      "피해",
      "문을", // "문"만 남으면 한 글자라 조사를 떼지 않는다
      "막고",
      "버티던",
    ]);
  });

  it("keeps a word whose stem would be shorter than two characters", () => {
    expect(queryTerms("물에 잠긴 집으로")).toEqual(["물에", "잠긴", "집으로"]);
  });
});

describe("highlight", () => {
  it("marks the longest matching terms in the caption", () => {
    expect(highlight("물에 잠긴 반지하 계단", ["물에", "잠긴", "계단"])).toEqual([
      { text: "물에", match: true },
      { text: " ", match: false },
      { text: "잠긴", match: true },
      { text: " 반지하 ", match: false },
      { text: "계단", match: true },
    ]);
  });

  it("returns the caption as is when there is nothing to match", () => {
    expect(highlight("밤의 골목", [])).toEqual([{ text: "밤의 골목", match: false }]);
    expect(highlight("밤의 골목", ["기차"])).toEqual([{ text: "밤의 골목", match: false }]);
  });

  it("escapes regex characters in terms", () => {
    expect(highlight("a+b 장면", ["a+b"])[0]).toEqual({ text: "a+b", match: true });
  });
});
