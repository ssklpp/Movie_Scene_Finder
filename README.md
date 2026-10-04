# Movie Scene Finder (장면 기억 검색기)

기억나는 영화 장면을 글이나 사진으로 설명하면 어떤 영화인지 찾아 주는 검색 서비스입니다.

**데모: https://movie-scene-finder-pi.vercel.app**

> **개발 중입니다.** 검색 에이전트, API, 검색 화면을 배포해 공개 URL에서 동작합니다. 실험과 최종 평가(Phase 6)가 남았습니다.
> 구현 순서와 상세 명세는 [SPEC.md](SPEC.md)를 따릅니다.

## 동작 방식

1. **오프라인 인덱싱** (`pipeline/`): TMDB에서 영화 300편과 장면 이미지를 모으고, 비슷한 이미지를 걸러 낸 뒤
   VLM으로 장면마다 한국어 설명(캡션)을 만듭니다. 캡션은 dense 임베딩과 BM25 sparse 벡터로 바꿔 Qdrant에 넣습니다.
2. **온라인 검색** (`backend/`): 사용자 묘사(또는 사진의 VLM 캡션)로 하이브리드 검색(dense + sparse, RRF)을 하고,
   장면 점수를 영화 단위로 모읍니다. 결과의 확신도가 낮으면 "몇 년도쯤 보셨나요?"처럼 최대 2번 되물어 후보를 좁힌 뒤
   Top 5 영화와 근거 장면을 돌려줍니다.

## 진행 상황

| Phase | 내용 | 상태 |
| --- | --- | --- |
| 0 | 저장소 구성, DB 스키마, CI | 완료 |
| 1 | 영화·이미지 수집, 중복 제거, 형태소 분석 사전, 평가 질의 수집 | 완료 |
| 2 | VLM 캡셔닝, Qdrant 적재 | 완료 |
| 3 | 하이브리드 검색, 첫 평가 | 완료 |
| 4 | LangGraph 에이전트(재질문), API | 완료 |
| 5 | 프론트엔드, 배포 | 완료 |
| 6 | 실험, 문서화 | 예정 |

지금까지 만든 데이터: 영화 300편(한국 영화 약 60편 포함), 이미지 4,446장, 중복을 걸러 낸 장면 3,852개와
장면마다의 한국어 캡션(`gpt-6-luna`, 검증 실패 0.18%), Qdrant 색인(장면 3,852개, 줄거리 299편),
결과 화면용 장면 썸네일 3,852장(Cloudflare R2),
사람이 직접 쓴 평가 질의 20개([작성 안내](eval/human_guide.md)), 합성 평가 질의 300개.

### 첫 평가 (E1, dev 합성 질의 200개, 질의 재작성·재질문 없이 검색만)

| 검색 방식 | Recall@1 | Recall@5 | MRR |
| --- | --- | --- | --- |
| dense | 0.100 | 0.235 | 0.156 |
| sparse (BM25) | 0.210 | 0.375 | 0.293 |
| hybrid (RRF) | 0.205 | 0.410 | 0.286 |

질의 재작성과 재질문(Phase 4)을 붙이기 전의 기준선입니다.

### 에이전트 평가 (E6, dev 합성 질의 200개, 재질문 최대 횟수 비교)

질의 재작성 → 하이브리드 검색 → LLM 검증 → 재질문을 모두 거친 결과입니다. 재질문에는 정답 영화의
연대·국가·장르로 자동 응답했습니다(사람이 정확히 기억한다는 가정이라 실제보다 유리합니다).

| 최대 재질문 | Recall@1 | Recall@5 | MRR | 평균 재질문 | 질의당 비용 |
| --- | --- | --- | --- | --- | --- |
| 0회 | 0.815 | 0.820 | 0.818 | 0 | 약 0.9원 |
| 1회 | 0.825 | 0.840 | 0.832 | 0.14회 | 약 1.0원 |
| 2회 | 0.860 | 0.875 | 0.867 | 0.28회 | 약 1.1원 |

응답 시간은 배포 환경(한국에서 순차 11회)에서 첫 검색 요청 중간값 4.4초, 가장 느린 경우 6.3초로 목표(p95 8초) 안입니다.
재질문에 답한 뒤의 요청은 약 3초입니다. 시간의 대부분은 OpenAI 호출(질의 재작성 약 2초, 검증 2~3초)이고 검색 자체는 약 0.3초입니다.
질의 재작성·검증 LLM의 추론을 끄자(`reasoning_effort=none`) 정확도는 그대로이고 응답이 약 2초 빨라졌으며, 추론이 길어져 10초 넘게 걸리던 경우도 거의 사라졌습니다(위 표는 그 전 측정). 최종 수치는 Phase 6에서 test 데이터(사람이 쓴 질의 포함)로 한 번 측정합니다.

## 기술 스택

- **Backend**: Python 3.12, FastAPI, SQLAlchemy + Alembic, PostgreSQL 16
- **Search**: Qdrant(dense + sparse), OpenAI 임베딩, Kiwi 형태소 분석(kiwipiepy)
- **Agent**: LangGraph (PostgresSaver 체크포인터로 재질문 대기 세션 보존), SSE 스트리밍
- **VLM 캡셔닝**: `gpt-6-luna`. 로컬 Qwen3-VL-4B(AWQ 4비트, vLLM)와 비교해 결정
- **Frontend**: Next.js 16, TypeScript, Tailwind
- **배포**: Railway(backend, PostgreSQL), Vercel(frontend), Qdrant Cloud, Cloudflare R2(썸네일)
- **Tooling**: uv, pnpm, ruff, mypy `--strict`, pytest, GitHub Actions
- **관측**: LangSmith(요청별 노드·LLM 호출 추적, 사용자 사진은 가려서 기록)

## 시작하기

Windows에서는 WSL2(Ubuntu) 안에서 실행합니다. 저장소도 WSL 홈 아래에 두세요(`/mnt/c/...` 아래에 두지 않습니다).

**필요한 것**: Docker(Compose 포함), [uv](https://docs.astral.sh/uv/), Node.js 22 + pnpm, make, TMDB API 읽기 액세스 토큰, OpenAI API 키

```bash
git clone https://github.com/ssklpp/Movie_Scene_Finder.git
cd Movie_Scene_Finder

cp .env.example .env          # TMDB_READ_TOKEN 등 키를 채운다
uv sync                        # Python 3.12 가상환경과 의존성
pnpm -C frontend install

make up                        # Qdrant(:6333), PostgreSQL(:5432)
make migrate                   # DB 스키마 생성
make test                      # 테스트
```

### 인덱싱 (Phase 1~2)

`make index`(또는 `make index LIMIT=20`)가 아래 단계를 순서대로 실행합니다. TMDB 토큰과 OpenAI 키가 필요합니다.

```bash
uv run python -m pipeline.s01_collect_meta      # 영화 300편 메타데이터 → movies
uv run python -m pipeline.s02_collect_images    # 영화별 장면 이미지 최대 15장 → pipeline/data/images/
uv run python -m pipeline.s03_dedup             # 비슷한 이미지 제거 → scenes
uv run python -m pipeline.build_user_dict       # 제목·인물명 형태소 분석 사전
uv run python -m pipeline.s04_caption           # 장면 캡션(VLM) → scenes.caption_*
uv run python -m pipeline.s05_validate          # 캡션 검증·재시도, 검수 표본 → reports/
uv run python -m pipeline.s06_build_docs        # 검색 문서(제목 제외)
uv run python -m pipeline.s07_embed             # dense·sparse(BM25) 벡터
uv run python -m pipeline.s08_upload            # Qdrant 적재, 별칭 scenes 교체, 썸네일 R2 업로드
```

- 대부분의 단계에 `--limit N`(앞 N편만 처리)과 `--force`(이미 처리한 것도 다시)를 줄 수 있습니다.
- 다시 실행하면 처리한 항목은 건너뜁니다. 진행 상태는 `pipeline/data/state.sqlite`에 남습니다.
- 수집한 이미지와 중간 결과(`pipeline/data/`)는 저장소에 올리지 않습니다.
- 썸네일 업로드는 `.env`에 R2 키(`R2_ACCOUNT_ID` 등)가 있을 때만 합니다. 없으면 건너뛰고 결과 화면에는 캡션만 나옵니다.

### 검색 API (Phase 4)

인덱싱을 마친 뒤 서버를 띄우면 SSE 스트림으로 검색할 수 있습니다.

```bash
uv run uvicorn app.main:app --port 8000 --app-dir backend

# 텍스트(또는 -F image=@still.jpg)로 검색: session → status → question 또는 result 이벤트
curl -N -X POST localhost:8000/search -F 'text=기차 안에서 좀비를 피해 문을 막고 버티는 영화'

# question 이벤트를 받았으면 선택지 값으로 답한다
curl -N -X POST localhost:8000/search/<session_id>/answer \
  -H 'Content-Type: application/json' -d '{"value": "2010s"}'
```

그 밖에 `POST /feedback`, `GET /movies/{id}`, `GET /health`가 있습니다([SPEC §9](SPEC.md)).

### 검색 화면 (Phase 5)

```bash
cp frontend/.env.example frontend/.env.local   # NEXT_PUBLIC_API_URL
make dev                                        # backend(:8000) + frontend(:3000)
```

브라우저에서 `http://localhost:3000`을 열고 기억나는 장면을 적거나 사진을 올립니다.
진행 단계, 재질문 선택지, 결과(포스터, 추천 이유, 근거 장면 썸네일과 질의 단어가 강조된 캡션, "맞아요/아니에요")가 차례로 나옵니다.
썸네일은 backend `.env`의 `R2_PUBLIC_URL`(R2 버킷 공개 주소)이 있을 때만 나옵니다.

### 배포

| 구성 | 위치 | 설정 |
| --- | --- | --- |
| frontend | Vercel (Root Directory `frontend`) | `NEXT_PUBLIC_API_URL` = backend 주소 |
| backend | Railway (`backend/Dockerfile`, `railway.json`) | `.env.example`의 값, `DATABASE_URL`, `CORS_ORIGINS`(Vercel 주소), `R2_PUBLIC_URL`, (추적 시) `LANGSMITH_TRACING=true`·`LANGSMITH_API_KEY` |
| PostgreSQL | Railway | backend 시작 시 `alembic upgrade head`. 영화·장면 목록은 `scripts/copy_catalog.sh <DATABASE_URL>`로 로컬에서 복사 |
| Qdrant | Qdrant Cloud | 로컬 `.env`의 `QDRANT_URL`·`QDRANT_API_KEY`를 클라우드로 바꾸고 `s08_upload` 실행 |
| 썸네일 | Cloudflare R2 (r2.dev 공개 주소) | 로컬에서 `s08_upload`가 업로드. R2 키는 로컬에만 둔다 |

### 평가

```bash
uv run python -m eval.make_synthetic                      # 합성 질의 300개 (이미 저장소에 있음)
uv run python -m eval.run_eval --config eval/configs/E1_hybrid.yaml --split dev --no-agent  # 검색만
uv run python -m eval.run_eval --config eval/configs/E6_turns2.yaml --split dev             # 에이전트
uv run python -m eval.report --experiment E6 --split dev  # 실험 비교표
```

### 개발 명령

```bash
uv run ruff check . && uv run ruff format .
uv run mypy backend pipeline
uv run pytest pipeline/tests/test_s03.py::test_hamming   # 테스트 하나만
make dev                                                  # backend(:8000) + frontend(:3000)
```

## 저장소 구조

```
backend/    FastAPI 앱(app/), DB 모델, Alembic 마이그레이션, 검색 모듈(search/), 테스트
pipeline/   오프라인 인덱싱 단계(s01~s08)와 공용 모듈(common/)
eval/       평가 데이터셋(human 20개, synthetic 300개), 실험 설정, 평가 스크립트
scripts/    로컬 VLM(vLLM) 실행, 배포 DB 카탈로그 복사 스크립트
frontend/   Next.js 앱 (검색 화면)
SPEC.md     구현 명세
```

## 데이터 출처

영화 정보와 이미지는 [TMDB](https://www.themoviedb.org/)에서 가져옵니다.

This product uses the TMDB API but is not endorsed or certified by TMDB.
