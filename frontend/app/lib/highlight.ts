// 근거 장면 캡션에서 사용자가 쓴 단어를 찾아 강조할 구간으로 나눈다(SPEC §10).

// 조사를 떼야 "기차에서"와 "기차"가 맞는다. 긴 것부터 떼어 낸다.
const PARTICLES = [
  "에서는", "으로는", "에서", "으로", "에게", "까지", "부터", "처럼", "하고",
  "이랑", "랑", "은", "는", "이", "가", "을", "를", "에", "로", "와", "과", "도", "의", "만",
];

// 거의 모든 질의와 캡션에 나와서 강조해도 도움이 안 되는 말
const STOPWORDS = new Set([
  "장면", "영화", "안에서", "안에", "같은데", "같아요", "기억", "있었는데", "있던", "나오던",
  "나오는", "하던", "있는", "그리고", "어떤", "누군가",
]);

export function queryTerms(query: string): string[] {
  const terms = new Set<string>();
  for (const raw of query.split(/[\s,.!?~·]+/)) {
    let word = raw.trim();
    // 가장 긴 조사 하나만 본다. 떼면 한 글자만 남는 경우("집으로")는 그대로 둔다.
    // (그다음 짧은 조사 "로"를 떼면 "집으"처럼 엉뚱한 말이 된다.)
    const particle = PARTICLES.find((p) => word.length > p.length && word.endsWith(p));
    if (particle && word.length - particle.length >= 2) word = word.slice(0, -particle.length);
    if (word.length >= 2 && !STOPWORDS.has(word) && !STOPWORDS.has(raw.trim())) terms.add(word);
  }
  return [...terms];
}

export type Segment = { text: string; match: boolean };

export function highlight(caption: string, terms: string[]): Segment[] {
  if (!terms.length) return [{ text: caption, match: false }];
  const escaped = [...terms]
    .sort((a, b) => b.length - a.length)
    .map((t) => t.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"));
  const pattern = new RegExp(`(${escaped.join("|")})`, "g");
  return caption
    .split(pattern)
    .filter(Boolean)
    .map((text) => ({ text, match: terms.includes(text) }));
}
