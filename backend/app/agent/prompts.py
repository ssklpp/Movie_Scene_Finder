"""에이전트 LLM 프롬프트와 구조화 출력 스키마."""

from collections.abc import Sequence
from typing import Literal

from openai.types.chat import ChatCompletionMessageParam
from pydantic import BaseModel

from app.agent.movies import MovieInfo
from app.search.aggregate import MovieCandidate
from app.search.caption import SceneCaption

# --- rewrite_query (SPEC §7.1) ---------------------------------------------


class SoftFilterFields(BaseModel):
    """OpenAI strict 구조화 출력은 자유 키 dict를 받지 않아 고정 필드로 받는다."""

    decade: str | None  # "1990s", "2010s" 형식
    country: Literal["KR", "other"] | None
    genre: str | None
    is_animation: Literal["true", "false"] | None


class RewriteOutput(BaseModel):
    scene_ko: str
    keywords_ko: list[str]
    soft_filters: SoftFilterFields


REWRITE_SYSTEM = """너는 영화 장면 검색기의 질의 정리 담당이다.
사용자가 기억나는 영화 장면을 흐릿하게 묘사하면 검색에 쓸 형태로 정리한다.

- scene_ko: 화면에 보였을 장면을 구체적인 한국어 한두 문장으로. 장소, 인물의 겉모습과 행동,
  물건, 색, 시간대처럼 눈에 보이는 것을 담는다. 사용자가 말하지 않은 내용은 지어내지 않는다.
- keywords_ko: 검색에 도움이 될 한국어 명사·동사 3~8개.
- soft_filters: 사용자가 영화의 조건을 말했을 때만 채운다. 말하지 않았으면 null.
  - decade: 개봉 연대, "1990s"·"2010s" 형식 ("2000년대쯤?" → "2000s")
  - country: 한국 영화면 "KR", 외국 영화면 "other"
  - genre: 아래 장르 목록 중 하나
  - is_animation: 애니메이션이면 "true", 실사 영화면 "false"
- 영화 제목이나 배우 이름을 말했더라도 scene_ko와 keywords_ko에는 넣지 않는다.

장르 목록: {genres}"""


def rewrite_messages(
    query_text: str | None, image_caption: SceneCaption | None, genres: Sequence[str]
) -> list[ChatCompletionMessageParam]:
    parts = []
    if query_text:
        parts.append(f"사용자 묘사: {query_text}")
    if image_caption:
        parts.append(
            "사용자가 올린 사진의 묘사: "
            f"{image_caption.caption_ko} (장소: {image_caption.setting}, "
            f"물건: {', '.join(image_caption.objects)})"
        )
    return [
        {"role": "system", "content": REWRITE_SYSTEM.format(genres=", ".join(genres))},
        {"role": "user", "content": "\n".join(parts)},
    ]


# --- verify (SPEC §7.5) ----------------------------------------------------

VERIFY_SYSTEM = """너는 영화 장면 검색 결과를 검증한다.
사용자의 기억과 후보 영화를 비교해, 후보마다 사용자가 찾는 영화일 가능성을 0~1 점수로 매긴다.

- 근거 장면 묘사와 사용자의 기억이 얼마나 맞는지 본다. 사용자의 기억은 흐릿해서 색, 수,
  시간대 같은 세부가 틀릴 수 있다.
- 그 영화를 알고 있으면 영화 내용에 대한 지식도 함께 쓴다. 모르는 영화는 근거 장면만으로 판단한다.
- 제목의 글자가 묘사와 비슷하다는 이유로 점수를 올리지 않는다. 장면 내용으로만 판단한다.
- 묘사가 여러 영화에 흔한 장면(추격, 대화, 싸움 등)이고 이 영화만의 특징이 없으면, 어느 후보에도
  0.5보다 높은 점수를 주지 않는다.
- 후보 모두에게 점수를 준다. 둘 이상이 비슷하면 점수도 비슷하게 준다.
- reason: 왜 그 점수인지 사용자에게 보여줄 한국어 한 문장. 배우 이름은 쓰지 않는다.
- evidence_scene_ids: 판단에 쓴 근거 장면 id(없으면 빈 목록)."""


def describe_user(query_text: str | None, image_caption: SceneCaption | None) -> str:
    parts = []
    if query_text:
        parts.append(f"사용자 묘사: {query_text}")
    if image_caption:
        parts.append(f"사용자가 올린 사진: {image_caption.caption_ko}")
    return "\n".join(parts)


def verify_messages(
    query_text: str | None,
    image_caption: SceneCaption | None,
    candidates: Sequence[MovieCandidate],
    infos: dict[int, MovieInfo],
) -> list[ChatCompletionMessageParam]:
    blocks = []
    for c in candidates:
        info = infos.get(c.movie_id)
        title = info.title_ko or info.title_en if info else None
        year = info.year if info else None
        lines = [f"movie_id={c.movie_id} | {title or '제목 미상'} ({year or '연도 미상'})"]
        lines += [f"  - [{h.scene_id}] {h.caption_ko}" for h in c.evidence]
        if not c.evidence:
            lines.append("  - (근거 장면 없음, 줄거리 검색으로만 찾음)")
        blocks.append("\n".join(lines))
    user = describe_user(query_text, image_caption) + "\n\n후보:\n" + "\n\n".join(blocks)
    return [
        {"role": "system", "content": VERIFY_SYSTEM},
        {"role": "user", "content": user},
    ]


# --- ask (SPEC §7.6: 질문 문장만 LLM이 만든다) --------------------------------

QUESTION_SYSTEM = """너는 영화 장면 검색기에서 사용자에게 되묻는 질문을 만든다.
정해진 항목에 대해, 선택지를 고르기 쉽게 묻는 짧고 친근한 한국어 질문 한 문장만 출력한다.
선택지는 따로 보여주므로 질문에 나열하지 않는다."""


def question_messages(
    attr_name: str, option_labels: Sequence[str], query_text: str | None
) -> list[ChatCompletionMessageParam]:
    user = (
        f"물어볼 항목: {attr_name}\n선택지: {', '.join(option_labels)}\n"
        f"사용자가 처음 한 말: {query_text or '(사진으로 검색)'}"
    )
    return [
        {"role": "system", "content": QUESTION_SYSTEM},
        {"role": "user", "content": user},
    ]
