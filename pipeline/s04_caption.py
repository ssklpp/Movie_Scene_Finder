"""s04: 장면 이미지를 VLM으로 묘사해 `SceneCaption`(SPEC §5.3)을 만들고 `scenes`에 저장한다.

백엔드는 `.env`의 CAPTION_BACKEND로 고른다. 둘 다 OpenAI 호환 클라이언트로
`core/llm.parse`를 거친다.
- local: 로컬 vLLM(`scripts/run_vlm.sh`), model_version = CAPTION_MODEL_VERSION
- openai: LLM_MODEL_DEFAULT 실시간 호출, model_version = "{모델}-{PROMPT_VERSION}"

`scene_id` + `model_version`이 이미 처리됐으면 건너뛴다. 실패한 장면은 캡션이 빈 채로 남고
s05가 다시 시도한다. `--sample N --out FILE`은 무작위 N장을 캡셔닝해 DB 대신 파일에만 쓴다
(캡션 모델 비교용).
"""

import argparse
import base64
import json
import logging
import random
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from openai import OpenAI
from openai.types.chat import ChatCompletionMessageParam
from sqlalchemy import select, update

from app.core import llm
from app.core.config import Settings, get_settings
from app.core.logging import setup_logging
from app.db.models import Movie, Scene
from app.db.session import SessionLocal
from pipeline.common.schemas import SceneCaption
from pipeline.common.state import State
from pipeline.s02_collect_images import image_path

logger = logging.getLogger(__name__)

STEP = "s04"
PROMPT_VERSION = "p1"

SYSTEM_PROMPT = """너는 영화 장면 이미지를 검색용으로 묘사한다.
사람들이 나중에 흐릿한 기억으로 이 장면을 찾는다.

규칙:
- 화면에 실제로 보이는 것만 쓴다. 줄거리나 보이지 않는 사건을 추측하지 않는다.
- 배우, 등장인물, 실존 인물의 이름과 영화 제목은 절대 쓰지 않는다. 알아보더라도 쓰지 않는다.
  인물은 "젊은 남자", "단발머리 소녀", "초록색 거인"처럼 겉모습으로 부른다.
- caption_ko: 자연스러운 한국어 한 문장, 40~120자.
  장소, 인물의 행동, 눈에 띄는 물건과 분위기를 담는다.
- caption_en: caption_ko와 같은 내용의 영어 한 문장.
- setting: 장소를 짧은 한국어로 (예: "비 오는 골목", "우주선 조종실").
- time_of_day: day, night, dawn, dusk 중 하나. 알 수 없으면 unknown.
- weather: 날씨가 보이면 짧은 한국어 (예: "비", "눈보라"), 실내이거나 알 수 없으면 null.
- people.count: 보이는 사람(또는 사람처럼 행동하는 캐릭터) 수.
  people.actions: 행동을 짧은 한국어 구로.
- objects: 눈에 띄는 물건 최대 8개, 한국어 명사.
- colors: 화면의 주요 색 최대 4개, 한국어.
- text_in_frame: 화면에 적힌 글자를 그대로. 없으면 null."""

USER_PROMPT = "이 영화 장면을 규칙에 맞춰 JSON으로 묘사해."


@dataclass(frozen=True)
class SceneJob:
    scene_id: str
    path: Path


@dataclass(frozen=True)
class CaptionResult:
    scene_id: str
    caption: SceneCaption | None
    error: str | None
    stats: llm.CallStats | None


def scene_image_path(scene_id: str, tmdb_id: int) -> Path:
    """scene id는 f"{tmdb_id}_backdrop_{n}" 형식이다(s03)."""
    n = int(scene_id.rsplit("_", 1)[1])
    return image_path(tmdb_id, n)


@dataclass(frozen=True)
class Backend:
    model: str
    model_version: str
    make_client: Callable[[], OpenAI]
    request_kwargs: dict[str, Any]


def backend_config(settings: Settings) -> Backend:
    """CAPTION_BACKEND별 모델, model_version, 클라이언트, 요청 옵션.

    gpt-6-luna는 추론 모델이라 temperature 대신 reasoning_effort(SPEC: low)를 쓴다.
    출력 한도(max_completion_tokens)에는 추론 토큰이 포함된다(100장 실측 평균 출력 254토큰).
    OpenAI는 요청마다 "입력 + 출력 한도"를 분당 토큰 한도(TPM)에서 미리 차감하므로,
    한도를 너무 크게 잡으면 429가 난다(계정 TPM 20만, 장당 입력 약 1,740토큰).
    """
    if settings.caption_backend == "local":
        return Backend(
            settings.local_vlm_model,
            settings.caption_model_version,
            llm.get_local_vlm_client,
            {"temperature": 0.2, "max_completion_tokens": 700},
        )
    if settings.caption_backend == "openai":
        model = settings.llm_model_default
        return Backend(
            model,
            f"{model}-{PROMPT_VERSION}",
            llm.get_client,
            {"reasoning_effort": "low", "max_completion_tokens": 1200},
        )
    raise SystemExit(f"CAPTION_BACKEND={settings.caption_backend} is not implemented yet")


def build_messages(image_bytes: bytes) -> list[ChatCompletionMessageParam]:
    b64 = base64.b64encode(image_bytes).decode()
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": [
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
                {"type": "text", "text": USER_PROMPT},
            ],
        },
    ]


def to_scene_values(caption: SceneCaption, model_version: str) -> dict[str, Any]:
    """`scenes` 업데이트 값. 캡션 문장 외 필드는 tags(JSONB)에 둔다."""
    return {
        "caption_ko": caption.caption_ko,
        "caption_en": caption.caption_en,
        "tags": caption.model_dump(exclude={"caption_ko", "caption_en"}),
        "model_version": model_version,
    }


def caption_one(
    job: SceneJob, model: str, client: OpenAI, request_kwargs: dict[str, Any]
) -> CaptionResult:
    try:
        caption, stats = llm.parse(
            build_messages(job.path.read_bytes()),
            SceneCaption,
            model=model,
            client=client,
            **request_kwargs,
        )
    except Exception as e:  # 스키마 불일치·길이 초과·연결 오류 모두 s05에서 다시 시도
        return CaptionResult(job.scene_id, None, f"{type(e).__name__}: {e}", None)
    if caption is None:
        return CaptionResult(job.scene_id, None, "refused", stats)
    return CaptionResult(job.scene_id, caption, None, stats)


def load_jobs(limit: int | None, sample: int | None, seed: int) -> list[SceneJob]:
    with SessionLocal() as session:
        movie_ids = select(Movie.id).order_by(Movie.id).limit(limit).scalar_subquery()
        stmt = (
            select(Scene.id, Movie.tmdb_id)
            .join(Movie, Scene.movie_id == Movie.id)
            .where(Movie.id.in_(movie_ids))
            .order_by(Scene.id)
        )
        rows = session.execute(stmt).all()
    jobs = [SceneJob(scene_id, scene_image_path(scene_id, tmdb_id)) for scene_id, tmdb_id in rows]
    if sample is not None:
        jobs = random.Random(seed).sample(jobs, min(sample, len(jobs)))
    return jobs


def save_caption(scene_id: str, values: dict[str, Any]) -> None:
    with SessionLocal.begin() as session:
        session.execute(update(Scene).where(Scene.id == scene_id).values(**values))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, help="movies 앞 N편의 장면만 처리 (s01과 같은 순서)")
    parser.add_argument("--force", action="store_true", help="이미 처리한 장면도 다시 캡셔닝")
    parser.add_argument("--sample", type=int, help="무작위 N장만 (고정 시드, 모델 비교용)")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--out", type=Path, help="결과를 DB 대신 이 jsonl 파일에만 쓴다")
    # 기본 3: local은 vLLM 동시 처리 한도, openai는 TPM 20만 안(분당 약 60건)에 들도록.
    parser.add_argument("--workers", type=int, default=3, help="동시 요청 수")
    args = parser.parse_args()
    setup_logging()
    for noisy in ("httpx", "httpx2", "app.core.llm"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    settings = get_settings()
    backend = backend_config(settings)
    model, model_version = backend.model, backend.model_version
    client = backend.make_client()
    workers = args.workers

    jobs = load_jobs(args.limit, args.sample, args.seed)
    state = State()
    if args.out is None and not args.force:
        jobs = [j for j in jobs if not state.is_done(STEP, j.scene_id, model_version)]
    logger.info(
        "s04: %d scenes, backend=%s model=%s version=%s workers=%d",
        len(jobs),
        settings.caption_backend,
        model,
        model_version,
        workers,
    )

    out_file = args.out.open("w", encoding="utf-8") if args.out else None
    ok = failed = in_tokens = out_tokens = 0
    cost = 0.0
    started = time.perf_counter()
    try:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [
                pool.submit(caption_one, j, model, client, backend.request_kwargs) for j in jobs
            ]
            for i, fut in enumerate(as_completed(futures), 1):
                r = fut.result()
                if r.stats:
                    in_tokens += r.stats.input_tokens
                    out_tokens += r.stats.output_tokens
                    cost += r.stats.cost_usd
                if out_file is not None:
                    out_file.write(
                        json.dumps(
                            {
                                "scene_id": r.scene_id,
                                "model_version": model_version,
                                "caption": r.caption.model_dump() if r.caption else None,
                                "error": r.error,
                                "latency_ms": r.stats.latency_ms if r.stats else None,
                            },
                            ensure_ascii=False,
                        )
                        + "\n"
                    )
                elif r.caption is not None:
                    save_caption(r.scene_id, to_scene_values(r.caption, model_version))
                    state.mark_done(STEP, r.scene_id, model_version)
                if r.caption is None:
                    failed += 1
                    logger.warning("scene %s failed: %s", r.scene_id, (r.error or "")[:200])
                else:
                    ok += 1
                if i % 50 == 0:
                    logger.info("progress %d/%d", i, len(jobs))
    finally:
        state.close()
        if out_file is not None:
            out_file.close()

    elapsed = time.perf_counter() - started
    logger.info(
        "s04 done: ok=%d failed=%d elapsed=%.0fs (%.2fs/scene) tokens in=%d out=%d cost_usd=%.4f",
        ok,
        failed,
        elapsed,
        elapsed / max(len(jobs), 1),
        in_tokens,
        out_tokens,
        cost,
    )


if __name__ == "__main__":
    main()
