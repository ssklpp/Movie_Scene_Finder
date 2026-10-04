# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

이 저장소는 @SPEC.md 를 따른다. 구현 순서, 데이터 모델, 검색 공식, API 계약의 기준은 SPEC.md이며, 이 파일과 충돌하면 SPEC.md가 우선한다.

## 현재 상태

- **현재 Phase: 0 (착수 준비)**. 스캐폴딩 완료, 로컬 기준(`make up && make migrate && make test`, `/health`) 통과. 남은 기준: GitHub 원격 저장소에 push해서 CI 녹색 확인. Phase 완료 기준(§12)을 통과하면 이 줄을 갱신한다.
- 현재 Phase의 완료 기준을 통과하기 전에는 다음 Phase 코드를 만들지 않는다.
- 저장소는 WSL 홈(`~/projects/movie-scene-finder`)에 있다. 모든 명령은 WSL2 셸에서 실행한다(`/mnt/c/...`나 Windows 쪽 Python·Node는 쓰지 않는다).
- Python 프로젝트는 backend·pipeline·eval이 함께 쓰는 uv workspace 하나로 만든다(`requires-python = ">=3.12,<3.13"`, §12 Phase 0). §3 트리에 보이는 `backend/pyproject.toml`은 workspace 멤버다.

## 명령 (Phase 0에서 만들 Makefile 기준)

```bash
make up            # docker compose: qdrant, postgres
make migrate       # alembic upgrade head
make test          # pytest
make dev           # backend(:8000) + frontend(:3000)
make index LIMIT=20  # 파이프라인 s01~s08 순차 실행
make eval

uv run pytest backend/tests/test_xxx.py::test_name   # 단일 테스트
uv run ruff check . && uv run ruff format .
uv run mypy --strict backend pipeline
uv run python -m pipeline.s04_caption --limit 100 [--force]
uv run python -m eval.run_eval --config eval/configs/E1_hybrid.yaml --split dev [--no-agent]
```

Python은 항상 `uv run`으로 실행한다(Python 3.12로 고정하고 시스템의 3.14는 쓰지 않는다). 프론트엔드는 pnpm과 Node 22를 쓴다. 로컬 VLM(vLLM, :8001)은 VRAM 8GB를 차지하므로 다른 GPU 작업과 동시에 띄우지 않는다.

## 아키텍처 요점

- **두 개의 실행 축**이 Qdrant와 Postgres를 공유한다. 오프라인 `pipeline/`은 수집 → pHash 중복 제거 → VLM 캡션 → 검색 문서 → dense/sparse 임베딩 → Qdrant `scenes_v{n}`에 적재한 뒤 alias `scenes`를 교체한다. 온라인 `backend/`는 LangGraph 에이전트(rewrite → retrieve → aggregate → verify → clarify/answer)를 FastAPI SSE로 노출한다.
- **sparse 토큰화 일치**: 인덱싱(s07)과 질의(backend)는 반드시 같은 `backend/app/search/sparse.py` 함수를 쓴다. BM25 `avgdl`은 s07이 `pipeline/data/bm25_stats.json`에 쓰고 backend가 읽는다. 한쪽만 바꾸면 검색이 조용히 망가진다.
- **검색 문서에는 영화 제목을 넣지 않는다**(s06).
- **필터 두 종류**: 사용자가 확신 없이 말한 조건은 `soft_filters`로 점수에 boost만 주고, 재질문으로 확정한 조건은 `hard_filters`로 두 prefetch에 payload 필터로 건다.
- **재질문 속성은 코드가 엔트로피로 고른다**(§7.6). LLM은 질문 문장만 생성한다.
- 에이전트 상태는 `PostgresSaver`(thread_id = session_id)에 저장되므로 서버를 재시작해도 `interrupt()`에서 대기 중인 세션을 재개할 수 있어야 한다.

## 구현 메모

- `core/llm.py`의 `chat()`·`embed()`는 `(결과, CallStats)`를 돌려준다. 세션·평가 비용은 `CallStats.cost_usd`를 합산해 기록한다. 재시도·타임아웃은 OpenAI SDK의 `max_retries`/`timeout`(설정 `http_max_retries`, `http_timeout_s`)으로 건다.
- 비용 단가는 `.env`의 `MODEL_PRICES_USD_PER_1M`(JSON, 모델별 `[input, output]` USD/1M 토큰)에서 읽는다. 단가가 없는 모델은 비용 0으로 기록하고 경고를 남긴다.
- ruff isort는 `app`, `pipeline`, `eval`을 first-party로 본다. `app`은 `backend/` 아래 패키지이며 workspace 멤버 `msf-backend`로 설치된다.
- 마이그레이션은 모델을 바꾼 뒤 `cd backend && uv run alembic revision --autogenerate -m "..."`로 만들고, 생성 파일을 검토한다.
- 프론트엔드는 Next.js 16이다. 코드를 쓰기 전에 `frontend/AGENTS.md`의 지시대로 `frontend/node_modules/next/dist/docs/`의 관련 문서를 먼저 읽는다.
- vLLM은 프로젝트 venv가 아닌 WSL의 `~/.venvs/vllm`(vllm 0.30.0)에 별도로 설치되어 있다. 모델 가중치는 아직 받지 않았다.

## 반드시 지킬 규칙 (SPEC §0 요약)

- 키와 모델 ID는 `.env` → `core/config.py`(pydantic-settings)에서만 읽는다. 하드코딩하지 않는다.
- 모든 LLM·임베딩 호출은 `core/llm.py` 래퍼를 거친다(모델, 토큰, USD 비용, 지연시간 로깅).
- 외부 API(TMDB, KMDb, OpenAI, Qdrant)에는 타임아웃과 지수 백오프 재시도(최대 3회)를 건다.
- 파이프라인은 멱등이어야 한다. `scene_id` + `model_version`이 이미 처리됐으면 건너뛰고, 진행 상태는 `pipeline/data/state.sqlite`에 기록한다.
- 예고편 처리는 `--with-trailers`를 줄 때만 실행한다. 원본 영상과 `pipeline/data/`는 커밋하지 않는다.
- VLM 캡션 프롬프트에 인물(배우) 이름을 생성하지 말라고 명시한다.
- 검색·집계·확신도·재질문 로직에는 단위 테스트를 작성하고, pytest·ruff·`mypy --strict`가 통과해야 커밋한다. 새 의존성을 추가하면 이유를 커밋 메시지에 적는다.
