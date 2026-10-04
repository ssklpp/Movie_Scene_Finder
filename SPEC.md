# SPEC: Movie Scene Finder (장면 기억 검색기)

> Claude Code용 구현 명세서. 이 문서를 저장소 루트에 두고, `CLAUDE.md`에서 `@SPEC.md`로 참조한다.
> Phase 순서대로 구현하고, 각 Phase의 완료 기준을 모두 통과한 뒤 다음 Phase로 넘어간다.

---

## 0. Claude Code 작업 규칙

1. Phase 단위로 작업한다. 현재 Phase의 완료 기준을 통과하기 전에는 다음 Phase 코드를 만들지 않는다.
2. API 키와 모델 ID는 코드에 하드코딩하지 않는다. 모든 설정은 `.env` → `core/config.py`(pydantic-settings)를 통해 읽는다.
3. LLM·임베딩 호출은 반드시 `core/llm.py`의 래퍼를 거친다. 래퍼는 모델명, 입출력 토큰, 비용(USD), 지연시간을 로깅한다.
4. 외부 API 호출(TMDB, KMDb, OpenAI, Qdrant)에는 재시도(지수 백오프, 최대 3회)와 타임아웃을 건다.
5. 파이프라인 스크립트는 멱등이어야 한다. 이미 처리한 항목(`scene_id` + `model_version`)은 건너뛴다.
6. 예고편 다운로드는 기본 비활성(`--with-trailers` 플래그로만 실행)이며, 원본 영상은 저장소·클라우드에 올리지 않는다.
7. 검색·집계·확신도·재질문 선택 로직에는 단위 테스트를 작성한다. `pytest`가 통과하지 않으면 커밋하지 않는다.
8. 타입 힌트를 모든 함수에 단다. 포맷터·린터는 `ruff`, 타입 체크는 `mypy --strict`(backend, pipeline).
9. 새 의존성을 추가할 때는 이유를 커밋 메시지에 적는다.
10. 인물 이름(배우명)을 VLM 캡션에 생성하지 않도록 프롬프트에 명시한다.
11. 모든 명령은 WSL2(Ubuntu) 셸에서 실행한다. Python은 `uv run`으로만 실행하며 시스템 Python을 직접 쓰지 않는다.
12. 로컬 VLM은 vLLM만 사용한다. vLLM 실행 중에는 VRAM 8GB를 점유하므로 다른 GPU 작업과 동시에 띄우지 않는다.

---

## 1. 프로젝트 정의

**목표**: 사용자가 장면 묘사(텍스트) 또는 화면 사진(이미지)을 입력하면, 사전에 구축한 장면 캡션 인덱스에서 하이브리드 검색으로 영화를 찾고, 확신도가 낮으면 최대 2회 재질문해 후보를 좁힌 뒤 Top 5와 근거 장면을 반환한다.

**MVP 범위 (In scope)**
- 영화 300편 (TMDB 인기작, 한국 영화 포함)
- 텍스트 질의, 이미지 질의(이미지 → VLM 캡션 → 텍스트 검색)
- 재질문 최대 2회 (선택지 버튼 방식)
- Top 5 결과 + 근거 장면 + 정답 피드백
- 평가 스크립트, 평가 결과 리포트, 내부 평가 대시보드

**제외 (Out of scope)**
- 로그인·개인화, 대사(음성) 검색, SigLIP 이미지 벡터 직접 검색, 신작 자동 반영 스케줄러, 1,000편 이상 확장

---

## 2. 기술 스택

| 영역 | 선택 |
| --- | --- |
| 개발 환경 | Windows + WSL2(Ubuntu). 저장소·Docker·vLLM·명령 실행은 모두 WSL 안에서 |
| 언어·패키지 | Python 3.12 (uv로 프로젝트 고정, 시스템의 3.14는 사용하지 않음) + uv, Node.js 22 LTS + pnpm |
| 백엔드 | FastAPI, Pydantic v2, pydantic-settings, SQLAlchemy 2 + Alembic, sse-starlette, slowapi |
| 에이전트 | LangGraph (PostgresSaver 체크포인터). LLM 호출은 `langchain-openai` 없이 `core/llm.py` 래퍼(OpenAI SDK)로 한다 |
| LLM | 기본 `gpt-6-luna` (reasoning effort low, verify만 none: 지연시간 때문, E6로 품질 확인), 고품질 폴백 `gpt-6.1-sol` |
| VLM | 대량 캡셔닝: `gpt-6-luna` 실시간 API(E2 비교로 결정). 비교용 로컬 `cyankiwi/Qwen3-VL-4B-Instruct-AWQ-4bit` (vLLM, OpenAI 호환 엔드포인트. 원본 Qwen3-VL-4B는 VRAM 8GB에 들어가지 않음) / 실시간 이미지: `gpt-6-luna` |
| 임베딩 | `text-embedding-3-small` (1536차원) |
| 형태소 분석 | kiwipiepy (사용자 사전: 영화 제목·인물명) |
| Vector DB | Qdrant (로컬 Docker / 배포 Qdrant Cloud 무료 1GB) |
| RDB | PostgreSQL 16 (로컬 Docker) / 배포 Railway(기본 버전 18, 쓰는 기능은 같음) |
| 이미지 처리 | Pillow, imagehash, (선택) ffmpeg + PySceneDetect |
| 파일 저장 | Cloudflare R2 (썸네일만, r2.dev 공개 주소로 제공) |
| 프론트엔드 | Next.js (App Router) + TypeScript + Tailwind |
| 관측·평가 | LangSmith, pytest |
| 배포 | Railway (backend + Postgres), Vercel (frontend), Qdrant Cloud |

> 모델 ID는 착수 시점에 OpenAI 콘솔·Hugging Face에서 정확한 값을 확인하고 `.env`에만 기록한다.

---

## 3. 저장소 구조

```
movie-scene-finder/
├── CLAUDE.md                  # "@SPEC.md 를 따른다" + 현재 Phase 메모
├── SPEC.md
├── .env.example
├── docker-compose.yml         # qdrant, postgres
├── Makefile
├── backend/
│   ├── pyproject.toml
│   ├── alembic/
│   └── app/
│       ├── main.py
│       ├── core/              # config.py, llm.py, cost.py, logging.py
│       ├── db/                # models.py, session.py
│       ├── search/            # sparse.py, embed.py, hybrid.py, aggregate.py, confidence.py, clarify.py
│       ├── agent/             # state.py, graph.py, prompts.py, nodes/*.py
│       └── api/               # routes_search.py, routes_feedback.py, routes_movies.py, schemas.py
│   └── tests/
├── pipeline/
│   ├── common/                # 공용 클라이언트·스키마
│   ├── s01_collect_meta.py
│   ├── s02_collect_images.py
│   ├── s03_dedup.py
│   ├── s04_caption.py
│   ├── s05_validate.py
│   ├── s06_build_docs.py
│   ├── s07_embed.py
│   ├── s08_upload.py
│   └── data/                  # .gitignore 대상 (이미지, 중간 산출물)
├── eval/
│   ├── datasets/              # *.jsonl (버전 태그 포함)
│   ├── configs/               # E1~E7 실험 설정 yaml
│   ├── make_synthetic.py
│   ├── run_eval.py
│   └── report.py
└── frontend/
    └── app/                   # page.tsx(검색), eval/page.tsx(내부 대시보드)
```

---

## 4. 환경 변수 (`.env.example`)

```dotenv
# OpenAI
OPENAI_API_KEY=
LLM_MODEL_DEFAULT=gpt-6-luna
LLM_MODEL_STRONG=gpt-6.1-sol
EMBED_MODEL=text-embedding-3-small
EMBED_DIM=1536
# 모델별 단가 (USD / 1M 토큰, [input, output]). 없는 모델은 비용 0으로 기록하고 경고
MODEL_PRICES_USD_PER_1M={}

# Caption backend: local (vLLM) | openai (LLM_MODEL_DEFAULT 실시간) | openai_batch (미구현)
CAPTION_BACKEND=openai
LOCAL_VLM_BASE_URL=http://localhost:8001/v1
LOCAL_VLM_MODEL=cyankiwi/Qwen3-VL-4B-Instruct-AWQ-4bit
CAPTION_MODEL_VERSION=qwen3vl4b-awq4-v1

# Data sources
TMDB_READ_TOKEN=
KMDB_API_KEY=

# Storage
DATABASE_URL=postgresql+psycopg://app:app@localhost:5432/msf
QDRANT_URL=http://localhost:6333
QDRANT_API_KEY=
QDRANT_SCENES_ALIAS=scenes
R2_ACCOUNT_ID=
R2_ACCESS_KEY_ID=
R2_SECRET_ACCESS_KEY=
R2_BUCKET=msf-thumbs
# 버킷 공개 주소(r2.dev 또는 연결 도메인). backend가 thumb_url을 만든다. 배포 backend에는 이것만 필요
R2_PUBLIC_URL=

# Search / agent
CONFIDENCE_THRESHOLD=0.7
MAX_CLARIFY_TURNS=2
SCENE_TOPK=50
MOVIE_TOPK=10
W_SECOND_SCENE=0.3
W_PLOT=0.5
SOFT_FILTER_BOOST=1.1
# 에이전트 LLM 추론 강도: none | low | medium | high
REWRITE_REASONING_EFFORT=low
VERIFY_REASONING_EFFORT=none

# Ops
RATE_LIMIT_PER_DAY=30
# 브라우저에서 API를 부를 프런트엔드 주소(JSON 배열)
CORS_ORIGINS=["http://localhost:3000"]
LANGSMITH_API_KEY=
LANGSMITH_PROJECT=movie-scene-finder
```

---

## 5. 데이터 모델

### 5.1 PostgreSQL

```sql
movies(
  id SERIAL PK, tmdb_id INT UNIQUE, title_ko TEXT, title_en TEXT,
  year INT, country TEXT, genres TEXT[], is_animation BOOL,
  plot_ko TEXT, poster_url TEXT
)
scenes(
  id TEXT PK,                 -- f"{tmdb_id}_{source}_{n}"
  movie_id INT FK, source TEXT CHECK (source IN ('backdrop','still','trailer')),
  r2_key TEXT, phash TEXT, caption_ko TEXT, caption_en TEXT,
  tags JSONB, model_version TEXT, created_at TIMESTAMPTZ
)
sessions(
  id UUID PK, created_at TIMESTAMPTZ, query_text TEXT, image_key TEXT,
  rewritten JSONB, hard_filters JSONB, clarify_turns INT,
  result_movie_ids INT[], confidence REAL, latency_ms INT, cost_usd NUMERIC(10,6)
)
feedback(id SERIAL PK, session_id UUID FK, movie_id INT FK, is_correct BOOL, created_at TIMESTAMPTZ)
eval_runs(
  id SERIAL PK, dataset_version TEXT, split TEXT, config JSONB,
  recall_at_1 REAL, recall_at_5 REAL, mrr REAL,
  clarify_success REAL, avg_clarify REAL, p95_latency_ms INT, cost_per_query_usd REAL,
  created_at TIMESTAMPTZ
)
```

LangGraph 체크포인트 테이블은 `PostgresSaver.setup()`이 생성한다.

### 5.2 Qdrant

| 컬렉션 | 포인트 | named vectors | payload (인덱스 대상 *) |
| --- | --- | --- | --- |
| `scenes_v{n}` (alias `scenes`) | 장면 1개 | `dense`: 1536, Cosine / `sparse_ko`: sparse, modifier=IDF | movie_id*, year*, decade*, country*, genres*, is_animation*, source, caption_ko, model_version |
| `movies` | 영화 1편 | `plot_dense`: 1536, Cosine / `plot_sparse_ko`: sparse, modifier=IDF | movie_id*, year*, decade*, country*, genres*, is_animation* |

### 5.3 캡션 출력 스키마 (Pydantic)

```python
class People(BaseModel):
    count: int
    actions: list[str]


class SceneCaption(BaseModel):
    caption_ko: str  # 한 문장, 40~120자, 인물 이름 금지
    caption_en: str
    setting: str
    time_of_day: Literal["day", "night", "dawn", "dusk", "unknown"]
    weather: str | None
    people: People
    objects: list[str]
    colors: list[str]
    text_in_frame: str | None
```

---

## 6. 오프라인 파이프라인 명세

모든 스크립트는 `python -m pipeline.sXX_... [--limit N] [--force]` 형태로 실행하고, 진행 상황을 `pipeline/data/state.sqlite`에 기록해 재실행 시 이어서 처리한다.

| 스크립트 | 입력 | 처리 | 출력 |
| --- | --- | --- | --- |
| s01_collect_meta | TMDB discover (인기순, KR 포함 300편) | 상세·장르·국가·줄거리 수집, KMDb로 한국어 줄거리 보강 | `movies` 테이블 |
| s02_collect_images | movies | TMDB images에서 backdrop 최대 15장 다운로드 (TMDB 영화에는 still이 없음. `--with-trailers` 시 PySceneDetect 키프레임 추가) | `pipeline/data/images/` |
| s03_dedup | 이미지 | pHash 계산, 같은 영화 내 해밍 거리 ≤ 20 묶음에서 대표 1장 (backdrop에 자르기·확대·색 보정 사본이 많아 8로는 거의 걸러지지 않음) | `scenes` 행(캡션 비어 있음) |
| (build_user_dict) | movies | 제목 + 영화별 주요 배우 10명·감독의 한글 이름으로 Kiwi 사용자 사전 생성. s03 다음에 실행 | `backend/app/search/data/user_dict.txt` (저장소 포함, 배포 backend도 사용) |
| s04_caption | scenes | `CAPTION_BACKEND`에 따라 로컬 vLLM 또는 OpenAI 실시간 API로 `SceneCaption` 생성(동시 3개, `max_completion_tokens=1200`, TPM 한도 때문). 두 백엔드 모두 OpenAI 호환 클라이언트 사용. 프롬프트는 `search/caption.py`(이미지 질의와 공유) | `scenes.caption_*`, `tags` |
| s05_validate | scenes | Pydantic 검증 실패 재시도(최대 2회), 실패 목록 출력, 무작위 50개 검수용 CSV 생성 | `reports/caption_review.csv` |
| s06_build_docs | scenes, movies | 검색 문서 = caption_ko + setting + objects + 장르·연대 (제목 제외, 제목 로고가 있을 수 있어 text_in_frame도 제외) | `pipeline/data/search_docs.jsonl` |
| s07_embed | search_text, plot_ko | dense: OpenAI 임베딩(배치 100) / sparse: §7.2 BM25 가중치 | 벡터 파일(parquet) |
| s08_upload | 벡터, payload | 새 컬렉션 `scenes_v{n}` 생성 → upsert(256개 배치) → alias `scenes` 교체, 썸네일(긴 변 512px JPEG) R2 `thumbs/{scene_id}.jpg` 업로드 | Qdrant, R2, `scenes.r2_key` |

`make index` = s01~s08 순차 실행(s03 다음에 build_user_dict). `QDRANT_URL`만 바꾸면 로컬/클라우드 어디든 적재된다.

---

## 7. 검색 명세

### 7.1 질의 재작성 출력

```python
class Rewritten(BaseModel):
    scene_ko: str
    keywords_ko: list[str]
    soft_filters: dict[Literal["country", "decade", "genre", "is_animation"], str]
```
OpenAI strict 구조화 출력은 자유 키 dict를 받지 않으므로 LLM에서는 고정 필드로 받아 이 형태로 바꾸고, 형식이 틀린 값은 버린다.
사용자가 확신 없이 말한 조건만 `soft_filters`로 넣는다. 재질문에서 확정된 조건은 State의 `hard_filters`로 관리한다.

### 7.2 Sparse (BM25) 벡터

- 토큰화: Kiwi, 남길 품사 `NNG, NNP, XR, VV, VA, SL, SN`(Kiwi가 붙이는 활용 접미사 `VV-R` 등은 `-` 앞으로 비교). 동사·형용사는 어간만, 영어(SL)는 소문자. 사용자 사전에 영화 제목·인물명 등록.
- term id: `mmh3.hash(token, signed=False)`.
- 문서 측 값: `tf * (k1 + 1) / (tf + k1 * (1 - b + b * dl / avgdl))`, `k1=1.2`, `b=0.75`, `avgdl`은 s07에서 컬렉션별로 계산해 `pipeline/data/bm25_stats.json`에 저장한다. 질의 측 값은 1.0이라 backend는 이 파일을 읽지 않는다(배포 불필요).
- 질의 측 값: 등장 토큰마다 1.0. IDF는 Qdrant modifier가 계산한다.
- 인덱싱과 질의는 반드시 같은 `search/sparse.py` 함수를 사용한다.

### 7.3 하이브리드 검색

Qdrant Query API 한 번 호출: `prefetch=[dense limit 50, sparse_ko limit 50]`, `query=FusionQuery(RRF)`, `limit=SCENE_TOPK`. `hard_filters`는 두 prefetch 모두에 payload 필터로 적용한다. `movies` 컬렉션도 같은 방식으로 상위 20편을 조회한다.

### 7.4 영화 단위 집계

```
score(m) = s1 + W_SECOND_SCENE * s2 + W_PLOT * p_m
if m이 soft_filters를 하나 이상 만족: score(m) *= SOFT_FILTER_BOOST
```
s1, s2 = 해당 영화 장면 RRF 점수 1·2위(없으면 0), p_m = 줄거리 검색 RRF 점수(없으면 0). 상위 `MOVIE_TOPK`편과 영화별 근거 장면 최대 3개를 반환한다.

### 7.5 검증과 확신도

- `gpt-6-luna`에 사용자 묘사 + 후보 10편의 제목·연도·근거 캡션을 주고 영화별 `{movie_id, score: 0~1, reason}`을 structured output으로 받는다.
  - `evidence_scene_ids`는 받지 않는다. 근거 장면은 검색 결과에서 가져오고, 이 필드가 출력 토큰의 약 30%를 차지해 응답이 느려졌다. `reason`은 점수 상위 5편만 50자 이내로 쓴다(지연시간은 출력 토큰 수에 비례).
  - `reasoning_effort="none"`으로 부른다(`VERIFY_REASONING_EFFORT`). dev E6에서 low와 정확도가 같고 요청 p95가 약 1.9초 짧았다.
  - 제목·연도를 주어 LLM의 영화 지식을 쓰되, "제목 글자로 점수를 올리지 말 것", "흔한 장면이면 0.5 이하"를 프롬프트에 넣는다.
- 검증 점수로 재정렬한다. v1, v2 = 1·2위 점수.
- `confidence = 0.6 * v1 + 0.4 * min(1, (v1 - v2) / 0.3)`

### 7.6 재질문 속성 선택

- 후보 속성: `decade`, `country`(KR / 기타), `genre`(대표 장르), `is_animation`.
- 상위 5편에 대해 속성별로 검증 점수 가중 분포의 엔트로피를 계산하고, 이미 물은 속성을 제외한 최댓값 속성을 고른다.
- 최대 엔트로피가 0이면 재질문하지 않고 바로 답한다.
- 선택지 = 해당 속성의 고유값(최대 3개) + "모르겠어요". "모르겠어요"는 필터를 추가하지 않는다.
- 속성 선택은 코드로 하고, 질문 문장은 속성별 고정 문장(`search/clarify.py`의 `QUESTIONS`)이다. 처음에는 LLM이 생성했으나 재질문 요청마다 1.2~2.5초가 더해져 바꿨다.

---

## 8. LangGraph 명세

### 8.1 State

```python
class SearchState(TypedDict):
    session_id: str
    query_text: str | None
    image_key: str | None
    image_caption: SceneCaption | None
    rewritten: Rewritten | None
    hard_filters: dict[str, str]
    asked_attrs: list[str]
    scene_hits: list[SceneHit]
    plot_hits: list[PlotHit]
    movie_candidates: list[MovieCandidate]
    verified: list[Verified]
    confidence: float
    clarify_choice: ClarifyChoice | None  # verify가 고른 재질문 속성(없으면 답한다)
    clarify_turns: int
    pending_question: Question | None
    result: list[ResultItem] | None
    cost_usd: Annotated[float, operator.add]  # 노드는 이번에 쓴 비용만 돌려준다
    timings_ms: Annotated[dict[str, int], sum_timings]
```

상태에 넣는 pydantic 모델은 체크포인트에서 복원되도록 `agent/state.py`의 `STATE_MODELS`에 등록한다.

### 8.2 노드와 엣지

| 노드 | 처리 | 모델 |
| --- | --- | --- |
| `analyze_input` | 이미지가 있으면 `SceneCaption` 생성 | gpt-6-luna (vision) |
| `rewrite_query` | 텍스트 + 이미지 캡션 → `Rewritten` | gpt-6-luna |
| `retrieve` | §7.3 | Qdrant + 임베딩 |
| `aggregate` | §7.4 | 코드 |
| `verify` | §7.5 | gpt-6-luna |
| `ask` | §7.6으로 고른 속성의 질문(고정 문장)과 선택지를 `pending_question`에 넣는다 | 코드 |
| `clarify` | `interrupt()` → 답을 `hard_filters`에 추가, `clarify_turns += 1` | 코드 |
| `answer` | Top 5 + 근거 장면(썸네일 URL) + 추천 이유 한 줄(verify의 `reason`을 그대로 씀) | 코드 |

`ask`와 `clarify`를 나눈 이유: LangGraph는 재개할 때 `interrupt()`가 있는 노드를 처음부터 다시 실행하므로, 질문 만들기를 같은 노드에 두면 재개 때 질문이 다시 만들어진다.

```
START → analyze_input → rewrite_query → retrieve → aggregate → verify
verify --(confidence ≥ THRESHOLD or clarify_turns ≥ MAX or 엔트로피 0)--> answer → END
verify --(그 외)--> ask → clarify → retrieve
```

체크포인터: `PostgresSaver`, `thread_id = session_id`. 재개: `graph.invoke(Command(resume=<선택값>), config={"configurable": {"thread_id": session_id}})`.

---

## 9. API 명세

| 메서드·경로 | 요청 | 응답 |
| --- | --- | --- |
| `POST /search` | multipart: `text?`, `image?` (JPEG/PNG, ≤5MB) — 둘 중 하나 이상 필수 | SSE 스트림, 첫 이벤트에 `session_id` |
| `POST /search/{session_id}/answer` | `{"value": "2000s"}` | SSE 스트림 (재개) |
| `POST /feedback` | `{"session_id", "movie_id", "is_correct"}` | `204` |
| `GET /movies/{id}` | - | 영화 상세 + 근거 장면 |
| `GET /health` | - | `{"status": "ok"}` |

**SSE 이벤트**

```
event: session    data: {"session_id": "..."}
event: status     data: {"step": "rewrite|retrieve|verify", "message": "..."}
event: question   data: {"text": "언제쯤 나온 영화였는지 기억나세요?", "options": ["2000s", "2010s", "unknown"], "labels": ["2000년대", "2010년대", "모르겠어요"], "attr": "decade"}
event: result     data: {"items": [{"movie_id", "title_ko", "year", "poster_url", "score", "reason", "evidence": [{"scene_id", "thumb_url", "caption_ko"}]}], "confidence": 0.82}
event: error      data: {"code": "...", "message": "..."}
```

`question`의 `labels`는 화면에 보일 선택지 이름이고, 답할 때는 `options`의 값을 보낸다. `thumb_url`은 `R2_PUBLIC_URL` + `thumbs/{scene_id}.jpg`이며 `R2_PUBLIC_URL`이 없으면 null이다.

보호 장치: IP당 하루 `RATE_LIMIT_PER_DAY`회(`/search`만 센다. 배포 시 프록시의 `X-Forwarded-For`로 IP를 구한다), 세션당 재질문 `MAX_CLARIFY_TURNS`회, 요청 타임아웃 30초. 세션 종료 시 `sessions`에 비용·지연시간(노드 처리 시간 합, 사용자가 답을 고르는 시간 제외)을 기록한다.

---

## 10. 프론트엔드 명세

- `/` 검색 화면: 텍스트 입력 + 이미지 드래그앤드롭, 예시 질의 칩 3개
- 진행 표시: `status` 이벤트를 단계 체크리스트로 표시
- 재질문 카드: `question` 이벤트 → 선택지 버튼 → `POST /search/{id}/answer`
- 결과: 영화 카드 5개(포스터, 제목, 연도, 추천 이유), 근거 장면 썸네일과 캡션(질의 키워드 하이라이트), "맞아요 / 아니에요" 버튼
- `/eval` 내부 대시보드: `eval_runs` 실험별 Recall@1·@5·MRR·비용·p95 표와 막대 차트
- 푸터에 TMDB 출처 표기. 예고편 프레임 원본은 노출하지 않는다.

---

## 11. 평가 명세

**데이터셋 형식** (`eval/datasets/*.jsonl`)

```json
{"id": "syn-0001", "query": "...", "image_path": null, "answer_movie_id": 123, "source": "synthetic", "split": "dev", "version": "v1"}
```

| 데이터셋 | 생성 | 규모 | split |
| --- | --- | --- | --- |
| synthetic | `make_synthetic.py`: 장면 캡션을 `gpt-6.1-sol`이 "흐릿한 기억" 문체로 재작성. 원문 단어 50% 이상 교체, 세부 1개 의도적 왜곡 | 300 | dev 200 / test 100 |
| human | 지인 10명이 기억나는 장면을 자유 서술 | 50 | test |
| image | 원본 스틸 크롭·색 변경·모니터 촬영 | 100 | dev 50 / test 50 |
| regression | `feedback.is_correct = false` 세션 누적 | 가변 | test |

**지표와 MVP 목표**: human test 기준 Recall@1 ≥ 40%, Recall@5 ≥ 70%, 평균 재질문 ≤ 0.8회, p95 ≤ 8초, 질의당 비용 ≤ 10원. 첫 측정 후 목표를 조정할 수 있다.

**실행**: `uv run python -m eval.run_eval --config eval/configs/E1_hybrid.yaml --split dev` → `eval_runs` 기록 + `reports/eval_{timestamp}.md` 생성. 재질문 평가 시에는 정답 영화 속성으로 자동 응답하는 시뮬레이터를 사용한다.

**실험 설정 (`eval/configs/`)**

| ID | 비교 대상 |
| --- | --- |
| E1 | dense only / sparse only / hybrid RRF |
| E2 | 캡션 모델: Qwen3-VL-4B / CapRL-Qwen3VL-4B / gpt-6-luna |
| E3 | 검색 문서 언어: caption_ko / caption_en / 둘 다 |
| E4 | 토크나이저: Kiwi / Kiwi+사용자 사전 / MeCab-ko / 문자 2-gram |
| E5 | W_PLOT: 0 / 0.5 / 1.0 |
| E6 | MAX_CLARIFY_TURNS: 0 / 1 / 2 |
| E7 | EMBED_DIM: 512 / 1536 |

---

## 12. 진행 단계 (시작부터 종료까지)

### Phase 0 — 착수 준비 (0.5주)

**사전 준비 (사람이 직접)**
- [ ] 계정·키 발급: OpenAI(월 사용 한도 설정), TMDB(Read Access Token), KMDb, Qdrant Cloud, Railway, Vercel, Cloudflare R2, LangSmith, GitHub
- [ ] Windows: NVIDIA 드라이버 최신화(`nvidia-smi`로 RTX 4060 8GB 확인), WSL2 + Ubuntu 설치(`wsl -l -v`에서 VERSION 2)
- [ ] `%UserProfile%\.wslconfig`에 `[wsl2]` / `memory=24GB` 설정 후 `wsl --shutdown`으로 재시작
- [ ] Docker Desktop: "Use WSL 2 based engine" + WSL Integration(Ubuntu) 활성화, WSL에서 `docker run hello-world` 성공
- [ ] WSL 안 설치: `sudo apt install -y git make build-essential`, uv 설치 후 `uv python install 3.12`, Node 22(nvm) + `corepack enable`(pnpm)
- [ ] WSL 안에서 `nvidia-smi`가 GPU를 인식하는지 확인 → vLLM 전용 venv(Python 3.12)에 vLLM 설치
- [ ] 저장소는 WSL 홈(`~/projects/movie-scene-finder`)에 생성 (`/mnt/c/...` 사용 금지)
- [ ] 디스크 여유 50GB 이상, 포트 5432·6333·8000·8001·3000 비어 있음 확인

환경 점검 스크립트 (WSL에서 실행, 모두 통과해야 Phase 0 진행):

```bash
nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv
docker --version && docker compose version
uv --version; node -v; pnpm -v; git --version; make -v | head -1
uv python list | grep 3.12
df -h ~ | tail -1
ss -ltn | grep -E ':(5432|6333|8000|8001|3000)\s' || echo "ports free"
```

**Claude Code 작업**
- [ ] 저장소 구조(§3) 생성, `uv python pin 3.12`, `pyproject.toml`(backend·pipeline·eval 공용 workspace, `requires-python = ">=3.12,<3.13"`), `frontend` Next.js 초기화(`engines.node >= 22`)
- [ ] `docker-compose.yml`(qdrant:latest, postgres:16), `.env.example`(§4), `Makefile`(`up`, `down`, `migrate`, `index`, `eval`, `test`, `dev`)
- [ ] `core/config.py`, `core/llm.py`(비용 로깅 래퍼), Alembic 초기 마이그레이션(§5.1)
- [ ] `GET /health`, `pytest` 기본 테스트, GitHub Actions CI(ruff + mypy + pytest)

**완료 기준**: `make up && make migrate && make test` 성공, `curl localhost:8000/health` → ok, CI 녹색.

### Phase 1 — 데이터 수집 (1주차)

- [ ] s01, s02, s03 구현
- [ ] 영화 제목·인물명으로 Kiwi 사용자 사전 생성 (`backend/app/search/data/user_dict.txt`, 배포 backend도 같은 사전을 써야 해서 저장소에 포함)
- [ ] 골든셋 초안: human 질의 수집 양식 작성, 우선 20개 확보

**완료 기준**: `movies` 300행, 이미지 4,000장 이상, 중복 제거 후 `scenes` 약 3,500행.

### Phase 2 — 캡셔닝과 적재 (2주차)

- [ ] vLLM 서버 실행 스크립트 (`scripts/run_vlm.sh`: `--max-model-len 4096 --gpu-memory-utilization 0.85`, 이미지 최대 픽셀 제한)
- [ ] s04 구현 → 100장으로 Qwen3-VL-4B / CapRL-Qwen3VL-4B / gpt-6-luna 비교 (품질 수동 확인 + 장당 시간 + VRAM)
- [ ] 선택한 모델로 전량 캡셔닝, s05 검증, 검수 50장
- [ ] s06, s07, s08 구현, 로컬 Qdrant 적재

**완료 기준**: 캡션 검증 실패율 < 2%, 검수 50장 중 환각 기록, 로컬 Qdrant `scenes` 포인트 수 = `scenes` 행 수.

### Phase 3 — 검색과 첫 평가 (3주차)

- [ ] `search/` 모듈(§7.2~7.4) + 단위 테스트
- [ ] `make_synthetic.py`로 synthetic 300개 생성
- [ ] `run_eval.py` (검색만 평가하는 `--no-agent` 모드 포함), E1 실행

**완료 기준**: E1 결과표(dense/sparse/hybrid의 Recall@1·@5·MRR) 생성, hybrid가 dev에서 dense 단독 대비 개선 여부 확인.

### Phase 4 — 에이전트와 API (4주차)

- [ ] `agent/` (§8): 노드, 조건부 엣지, `interrupt`, PostgresSaver
- [ ] `search/confidence.py`, `search/clarify.py` + 단위 테스트
- [ ] API(§9): SSE, 재개, 피드백, rate limit
- [ ] 재질문 시뮬레이터로 E6 실행

**완료 기준**: `curl`로 시나리오 1(텍스트 → 재질문 → 답 → 결과) 성공, 서버 재시작 후에도 대기 중 세션 재개 가능, E6 결과표 생성.

### Phase 5 — 프론트엔드와 배포 (5주차)

- [ ] 프론트엔드(§10) 검색·재질문·결과 화면, 이미지 업로드
- [ ] 배포
  1. Railway: Postgres 생성 → `DATABASE_URL` 설정 → `alembic upgrade head` → `scripts/copy_catalog.sh`로 로컬의 movies·scenes 복사
  2. Qdrant Cloud: 클러스터 생성 → 로컬에서 `QDRANT_URL`/`QDRANT_API_KEY`를 클라우드로 바꿔 `s08_upload` 실행
  3. Railway: backend 서비스(Dockerfile), 환경 변수 등록, `/health` 헬스체크
  4. Vercel: frontend 배포, `NEXT_PUBLIC_API_URL` 설정, backend `CORS_ORIGINS`에 Vercel 도메인 추가
  5. R2: 버킷 공개 주소(r2.dev)를 켜고 로컬에서 s08로 썸네일 업로드, backend에 `R2_PUBLIC_URL` 설정
  6. OpenAI 월 예산 한도, rate limit 동작 확인

**완료 기준**: 공개 URL에서 시나리오 1(텍스트)·2(이미지) 성공, 로컬 PC를 끈 상태에서도 동작.

### Phase 6 — 실험, 문서화, 종료 (6주차)

- [ ] E2~E5, E7 실행 → dev로 파라미터 확정 → test(synthetic test + human + image)로 최종 측정 1회
- [ ] `/eval` 대시보드
- [ ] `README.md`: 한 줄 소개, 데모 GIF, 아키텍처 그림, 실행 방법, 최종 평가표, 실험 결과 요약(E1~E7), 질의당 비용·월 운영비, 실패 사례 유형 분석, 한계와 다음 단계, 데이터 출처·라이선스
- [ ] 2분 데모 영상 (텍스트 질의 → 재질문 → 결과, 이미지 질의, 평가 대시보드)
- [ ] `v1.0.0` 태그, GitHub Release

**프로젝트 종료 체크리스트**
- [ ] 공개 URL 정상 동작, `/health` 녹색
- [ ] test 셋 최종 수치가 README와 `eval_runs`에 일치
- [ ] `.env`·키·원본 영상·자막이 저장소에 없음 (`git log` 포함 확인)
- [ ] OpenAI 예산 한도와 rate limit 설정 유지
- [ ] 모든 테스트·CI 통과
- [ ] README의 실행 방법대로 새 환경에서 `make up && make index LIMIT=20 && make dev` 재현 성공

---

## 13. 비용 기준 (확인용)

- 초기: 로컬 캡셔닝 시 전기료 수준, `gpt-6-luna` Batch 사용 시 수천 원
- 월 운영: Railway 약 0.7~1만 원 + 질의 비용(월 1,000회 기준 0.3~0.8만 원) ≈ 1~1.5만 원
- 질의당 목표: 10원 이하. `sessions.cost_usd`로 실측해 README에 기록한다.
