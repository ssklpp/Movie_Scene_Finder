# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

이 저장소는 @SPEC.md 를 따른다. 구현 순서, 데이터 모델, 검색 공식, API 계약의 기준은 SPEC.md이며, 이 파일과 충돌하면 SPEC.md가 우선한다.

## 현재 상태

- **현재 Phase: 5 (프론트엔드와 배포)**. Phase 0·1·2·3·4 완료(2026-10-04).
  - Phase 1 결과: movies 300편, 이미지 4,446장, scenes 3,852행, Kiwi 사용자 사전, human 질의 20개. KMDb 줄거리 보강은 API 키 발급 대기 중(완료 기준 밖).
  - Phase 2 결과: 캡션 3,852장(gpt-6-luna), 검증 실패 0.18%, 검수 50장 환각 0건, 로컬 Qdrant `scenes`(→ `scenes_v2`) 3,852 포인트 = scenes 행 수, `movies` 299 포인트.
  - Phase 3 결과: `search/filters.py`·`hybrid.py`·`aggregate.py`, synthetic 300개, `eval/run_eval.py`·`report.py`, E1 결과표(아래 구현 메모). hybrid가 dev에서 dense보다 나음을 확인했다.
  - Phase 4 결과: `search/confidence.py`·`clarify.py`, `agent/`(LangGraph, PostgresSaver), API(SSE·재개·피드백·rate limit), 재질문 시뮬레이터, E6 결과표(아래 구현 메모). curl 시나리오 1과 서버 재시작 후 재개를 실제 서버로 확인했다.
  - Phase 5에 남은 것: 프론트엔드(§10: 검색·재질문·결과 화면, 이미지 업로드), 배포(Railway·Qdrant Cloud·Vercel, CORS), R2 썸네일(s08 업로드와 thumb_url), 사용자 사전·bm25_stats를 backend 배포에 포함하는 방법. **지연시간(요청 p95 약 10초, SPEC 목표 8초)** 개선 과제도 남아 있다.
  - 원격 저장소: https://github.com/ssklpp/Movie_Scene_Finder. Phase 완료 기준(§12)을 통과하면 이 항목을 갱신한다.
- 현재 Phase의 완료 기준을 통과하기 전에는 다음 Phase 코드를 만들지 않는다.
- 저장소는 WSL 홈(`~/projects/movie-scene-finder`)에 있다. 모든 명령은 WSL2 셸에서 실행한다(`/mnt/c/...`나 Windows 쪽 Python·Node는 쓰지 않는다).
- Python 프로젝트는 backend·pipeline·eval이 함께 쓰는 uv workspace 하나로 만든다(`requires-python = ">=3.12,<3.13"`, §12 Phase 0). §3 트리에 보이는 `backend/pyproject.toml`은 workspace 멤버다.

## 명령

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
- s02는 backdrop만 받는다(TMDB 영화에는 still이 없다). s03의 pHash 중복 기준은 SPEC의 8이 아니라 **20**이다. backdrop에 자르기·확대·색 보정 사본이 많아 8로는 거의 걸러지지 않았다(4,446장 → 8: 4,242행, 20: 3,852행). backdrop 중 홍보용 포스터 이미지가 많으니 Phase 2 s05 검수에서 비율을 확인한다.
- Kiwi 사용자 사전은 `uv run python -m pipeline.build_user_dict`로 만든다(`pipeline/data/user_dict.txt`, 제목 + 영화별 주요 배우 10명·감독의 한글 이름). 띄어 쓴 제목과 배역 이름(영어)은 넣지 않는다. 이 파일은 git에서 빠지지만 backend 질의 토큰화에도 필요하므로, Phase 5 배포 때 전달 방법을 정해야 한다. `kiwipiepy`는 타입 정보가 없어 mypy override로 제외했다.
- human 골든셋: 지인 입력 `eval/datasets/human_v1.csv`(안내문 `eval/human_guide.md`, 영화 목록 `movie_list_v1.csv`)를 `uv run python -m eval.human_dataset build`로 `human_v1.jsonl`로 바꾼다. 레코드에는 SPEC 필드 `answer_movie_id`(movies.id) 외에 `answer_tmdb_id`도 있다. DB를 새로 만들면 movies.id가 바뀔 수 있으니 평가 시 정답은 `answer_tmdb_id` 기준으로 맞춘다.
- **캡션 모델은 `gpt-6-luna`로 결정했다(2026-10-04, `CAPTION_BACKEND=openai`, model_version `gpt-6-luna-p1`).** 같은 무작위 100장(`s04 --sample 100 --seed 0`)으로 로컬 AWQ 4비트와 비교한 결과이며, SPEC E2(캡션 모델 비교)의 결과로 쓴다.

  | 항목 | 로컬 AWQ 4비트 | gpt-6-luna |
  | --- | --- | --- |
  | 성공 | 99/100 (1장 출력 반복으로 한도 초과) | 100/100 |
  | caption_ko 40~120자 | 91 | 100 |
  | 평균 길이 / 평균 물건 수 | 52자 / 4.7개 | 66자 / 4.3개 |
  | 인물 이름 사용 | 1건("스파이더맨") | 0건 |
  | 처리량(동시 요청) | 1.74초/장(3개) | 0.42초/장(8개) |
  | 토큰(입력/출력, 100장) | 129,690 / 22,470 | 174,300 / 25,444 |
  | 비용 | 0 | 100장 $0.030, 전체 3,852장 약 $1.2 |

  로컬 모델은 프롬프트 예시 문구("단발머리 소녀", "거인")를 실제 장면과 무관하게 베끼거나 단어가 깨지는("캐노eing") 문제가 있었다. gpt-6-luna는 추론 모델이라 `max_tokens`·`temperature`를 거부하므로 `reasoning_effort="low"`, `max_completion_tokens=2000`으로 호출한다(s04 `backend_config`). Batch API(반값)는 비용 차이가 작아 구현하지 않았다. 비교 결과 파일은 `reports/captions_cmp_*.jsonl`(git 제외)이다.
- 전체 캡셔닝 결과(2026-10-04): 3,852장 모두 `gpt-6-luna-p1`, 총 약 $1.1, 약 1시간. 계정 `gpt-6-luna` 한도가 **TPM 20만**이고 OpenAI는 "입력 + max_completion_tokens"를 미리 차감하므로, s04·s05는 동시 요청 3개, `max_completion_tokens=1200`을 쓴다(8개·2,000일 때 9%가 429로 실패했다).
- s05 검증: 실패 7장(0.18%, 목표 < 2%). 모두 알려진 오탐이다. 마이클(936075)의 "마이크"(출연진 이름 일부 = 마이크), 에이리언(348)의 "Alien"(영어 제목 = 외계인). 실패 장면도 캡션은 DB에 남아 있고, 재시도에서 규칙을 통과한 캡션만 덮어쓴다. 한 글자 예명("비")은 날씨와 겹쳐 검사에서 뺐다.
- 사람 검수(무작위 50장, `s05 --seed 0`, 2026-10-04): **환각 0건**, **홍보·합성 이미지 20장(40%)**. 홍보 이미지(정면 포즈, 단색 배경, 콜라주)의 캡션은 사용자가 기억하는 장면과 잘 맞지 않으므로, Phase 3 평가에서 이 이미지를 빼거나 가중치를 낮췄을 때 검색이 나아지는지 확인한다. 검수 파일은 `reports/caption_review.csv`(git 제외)다.
- s06은 검색 문서를 DB가 아닌 `pipeline/data/search_docs.jsonl`에 쓴다(SPEC 스키마에 search_text 컬럼이 없다). 화면 속 글자(text_in_frame)는 제목 로고가 있을 수 있어 넣지 않는다.
- `search/sparse.py`(SPEC §7.3 이전에 s07이 필요해 Phase 2에서 만들었다): Kiwi는 활용 종류를 품사 접미사로 붙이므로(`VV-R`, `VA-I`) 품사는 `-` 앞부분으로 비교한다. 영어(SL)는 소문자로 맞춘다. `bm25_stats.json`에는 컬렉션별 avgdl을 둔다(`scenes` 약 33.2, `movies` 약 54.6 토큰).
- s07 출력은 `pipeline/data/vectors/{scenes,movies}.parquet`. dense는 "모델|차원|문서" 해시로 캐시해 바뀐 문서만 다시 임베딩한다. 전체 임베딩 비용 약 $0.012. 줄거리가 없는 영화 1편은 `movies`에서 빠진다(p_m = 0).
- s08: 컬렉션·벡터 이름(`scenes_v{n}`, `movies`, `dense`, `sparse_ko`, `plot_dense`, `plot_sparse_ko`)과 연대 키(`"2010s"`)는 `search/qdrant.py`에 있고 검색도 이것을 쓴다. 포인트 ID는 scene_id의 UUID5이며 scene_id는 payload에 있다. 입력 parquet가 같으면 건너뛰므로 다시 적재하려면 `--force`. 시험용으로 만든 `scenes_v1`(41개)은 다음 적재 때 정리된다.
- `make index`는 s03 다음에 `build_user_dict`를 돌린다(s07 sparse 토큰화가 사전을 쓴다).
- synthetic 질의(`eval/datasets/synthetic_v1.jsonl`, `uv run python -m eval.make_synthetic`): 영화마다 장면 1개 → 300개(dev 200 / test 100, seed 0), gpt-6.1-sol, 비용 $0.46. 원문 Kiwi 토큰 겹침 ≤ 50%(중간값 19.5%)를 코드로 확인한다. 일부러 틀린 세부의 46%가 색이다. 캡션을 바꿔 쓴 질의라 human보다 쉬우므로 최종 판단은 human 기준으로 한다.
- 평가: `uv run python -m eval.run_eval --config eval/configs/E1_hybrid.yaml --split dev --no-agent` → `eval_runs` + `reports/eval_*.md`(1위가 아닌 질의 목록)·`.jsonl`(질의별 결과). 비교표는 `uv run python -m eval.report --experiment E1 --split dev`. 커밋 해시는 코드 변경이 남아 있으면 `-dirty`가 붙는다. `--limit`을 주면 `eval_runs`에 기록하지 않는다. 에이전트 평가는 Phase 4에서 추가한다.
- **E1 결과(dev, synthetic 200, `--no-agent`, 2026-10-04)**: dense R@1 0.100 / R@5 0.235 / MRR 0.156, sparse 0.210 / 0.375 / 0.293, **hybrid 0.205 / 0.410 / 0.286**. p95 < 0.2초. hybrid가 dense 대비 약 2배이고 sparse와는 비슷하다. dense가 약한 이유는 파이프라인 문제가 아니다(저장 벡터·Qdrant·전수 계산 순위 일치를 확인했다). 많이 바꿔 쓴 구어체 질의에서 text-embedding-3-small의 원문 장면 유사도가 비슷한 다른 장면보다 낮다. 개선 후보: Phase 4 질의 재작성(rewrite), dense 모델, RRF k(Qdrant 기본은 1/(1+순위)), 홍보 이미지 제외. 이 실행은 평가 코드 커밋 전이라 `eval_runs`의 커밋 값(`9e4d7c4`)에 평가 코드가 없다.
- test split(human 포함)은 SPEC대로 Phase 6 최종 측정 때 1회만 쓴다.
- 에이전트(`app/agent/`)에서 SPEC과 다르게 정한 것(사용자 확인, 2026-10-04):
  - SPEC의 clarify를 `ask`(질문 문장 LLM 생성)와 `clarify`(`interrupt()`·답 반영)로 나눴다. LangGraph는 재개할 때 interrupt가 있는 노드를 처음부터 다시 실행하므로, 한 노드에 두면 LLM이 다시 불리고 질문이 바뀐다.
  - `langchain-openai`를 쓰지 않는다. 모든 LLM 호출은 `core/llm.py` 래퍼(비용 기록)를 거친다.
  - answer 노드는 LLM을 부르지 않고 verify의 `reason`을 추천 이유로 쓴다.
  - 캡션 스키마·프롬프트는 `search/caption.py`에 있다(색인 s04와 이미지 질의가 같은 프롬프트를 쓴다).
  - rewrite의 soft_filters는 OpenAI strict 구조화 출력이 자유 키 dict를 받지 않아 고정 필드(`SoftFilterFields`)로 받고, 형식이 틀린 값은 코드에서 버린다.
  - verify 입력에 후보의 제목·연도를 준다(LLM의 영화 지식 활용). 대신 "제목 글자로 점수를 올리지 말 것", "흔한 장면이면 0.5 이하"를 프롬프트에 넣었다. 넣기 전에는 "누군가를 쫓아가는 장면"에 "추격자"를 0.88로 과신했다.
- API(§9): `agent/runtime.py`가 그래프를 돌려 SSE 이벤트를 만들고 세션을 기록한다(FastAPI 없이 테스트 가능). 서버는 시작할 때 Postgres 연결 풀 체크포인터로 그래프를 한 번 만든다(`main.py` lifespan). `question` 이벤트에는 SPEC 필드 외에 화면용 `labels`가 있다. `sessions.latency_ms`는 노드 처리 시간 합(사용자가 답을 기다린 시간 제외). rate limit은 `/search`만 센다. 테스트는 `app.state.runtime`에 메모리 체크포인터 실행기를 넣고 TestClient를 `with` 없이 써서 lifespan을 건너뛴다. DB 테스트는 Postgres가 없으면 skip되고 CI는 Postgres 서비스로 돌린다.
- 에이전트 평가: `uv run python -m eval.run_eval --config eval/configs/E6_turns2.yaml --split dev`(설정 `agent: true`, `--no-agent` 없이). 메모리 체크포인터로 돌리고 재질문은 `eval/simulator.py`가 정답 영화 속성으로 답한다(값이 선택지에 없으면 "모르겠어요"). 사람이 속성을 정확히 기억한다는 가정이라 실제보다 유리하다. 질의를 4개씩 동시에 돌린다(`--workers`). p95는 요청(invoke) 1회 기준이며 동시 실행 탓에 다소 높게 잡힌다. `clarify_success` = 재질문을 한 질의 중 최종 1위가 정답인 비율(SPEC에 정의가 없어 정함).
- **E6 결과(dev, synthetic 200, 시뮬레이터, 2026-10-04)**: turns0 R@1 0.815 / R@5 0.820 / MRR 0.818, turns1 0.825 / 0.840 / 0.832(평균 재질문 0.14, clarify_success 0.31), **turns2 0.860 / 0.875 / 0.867(평균 재질문 0.28, clarify_success 0.42)**. 요청 p95 10.2~11.1초, 질의당 $0.00065~0.00082(약 1원). 에이전트가 검색만 할 때(E1 hybrid R@1 0.205)보다 크게 낫다(재작성 + 영화 지식을 쓰는 검증). R@1과 R@5가 거의 같아, 못 찾는 질의는 대부분 정답이 후보 10편에 들지 않은 경우다. 이 실행의 커밋 값은 `ffc08d5-dirty`(평가 코드 커밋 전)다.
- 지연시간(2026-10-04 측정, dev 20개 순차): 요청 1회의 75%가 verify이고 그 시간은 **출력 토큰 수**에 비례한다(초당 약 90~120토큰, 추론 토큰은 적다). 그래서 verify 출력에서 SPEC의 `evidence_scene_ids`를 뺐고(쓰는 곳이 없었다), reason은 점수 상위 5편만 50자 이내로 쓰게 했다. 서버 시작 때 `agent/warmup.py`가 Kiwi·영화 목록·Qdrant·OpenAI 연결을 미리 준비한다(첫 요청 약 3초 단축).
  - 결과: verify 출력 740 → 390토큰, verify 6.2 → 4.3초, 요청 중간값 8.5 → 6.8초, p95 10.6 → 9.1초(순차). E6 turns2 재측정: R@1 0.860 → 0.840, R@5 0.875 → 0.860, 요청 p95(동시 4) 10.5 → 8.8초, 질의당 $0.00082 → $0.00064. 질의별로는 1위가 11개 틀려지고 7개 맞아져 LLM 응답의 무작위성 범위로 보이지만, 작은 하락이 없다고 확인하지는 않았다.
  - 아직 p95 > 8초다. 재질문으로 끝나는 첫 요청(재작성 2.2 + verify 4.3 + 질문 생성 1.2~2.5초)이 꼬리를 만든다. 남은 후보: 재질문 문장 고정(SPEC §7.6과 다름), rewrite·verify에 `reasoning_effort="none"`(gpt-6-luna는 `minimal`은 거부하고 `none`은 받는다, SPEC "low"와 다름).
- 체크포인트 상태의 pydantic 모델은 `agent/state.py`의 `STATE_MODELS`에 등록해야 복원된다(`checkpoint.make_serde`). 새 모델을 상태에 넣으면 여기에도 추가한다.
- 실제 실행 관찰(2026-10-04): 질의당 비용 약 $0.0006(재질문 2회 세션 약 $0.0018). **지연시간이 SPEC 목표를 넘는다**: verify 1회 약 7초, rewrite 1.5~3초 → 첫 응답 약 10초, 재질문마다 7~10초 추가. 서버 재시작 후 재개(새 연결·새 그래프)는 동작을 확인했다. 기생충 "물난리" 질의처럼 수집 이미지와 줄거리에 없는 장면은 재질문 후에도 후보에 들지 않는다.
- 로컬 VLM은 E2 재실험용으로 남겨 둔다. `scripts/run_vlm.sh`로 띄운다(vLLM은 프로젝트 venv가 아닌 `~/.venvs/vllm`, vllm 0.30.0). 시작에 약 100초 걸린다.
  - 모델은 SPEC의 원본 `Qwen/Qwen3-VL-4B-Instruct`가 아니라 **AWQ 4비트 양자화본 `cyankiwi/Qwen3-VL-4B-Instruct-AWQ-4bit`**다. 원본(8.9GB)은 VRAM에 안 들어가고, 공식 FP8(5.7GiB)은 최대 길이 3,072로 줄여야 했으며 시작 중 WSL이 재시작됐다. AWQ 4비트는 SPEC 설정(4,096, 0.85) 그대로 뜨고 KV 캐시 1.89GiB가 남는다. 캡션 1장 약 1~2초, 입력 약 930토큰.
  - Windows 화면 표시가 VRAM을 쓴다. 브라우저·Discord·Steam 등을 끄면 약 0.5GB가 늘어난다.
  - WSL에 CUDA 툴킷(nvcc)이 없어 FlashInfer JIT 컴파일이 실패한다. 그래서 스크립트가 `VLLM_USE_FLASHINFER_SAMPLER=0`을 설정하고, `--kv-cache-dtype fp8`은 쓰지 않는다.
  - CapRL-Qwen3VL-4B(9.7GB)는 vLLM용 양자화본이 없어 이 GPU에서 E2 비교 대상에서 빠진다.

## 반드시 지킬 규칙 (SPEC §0 요약)

- 키와 모델 ID는 `.env` → `core/config.py`(pydantic-settings)에서만 읽는다. 하드코딩하지 않는다.
- 모든 LLM·임베딩 호출은 `core/llm.py` 래퍼를 거친다(모델, 토큰, USD 비용, 지연시간 로깅).
- 외부 API(TMDB, KMDb, OpenAI, Qdrant)에는 타임아웃과 지수 백오프 재시도(최대 3회)를 건다.
- 파이프라인은 멱등이어야 한다. `scene_id` + `model_version`이 이미 처리됐으면 건너뛰고, 진행 상태는 `pipeline/data/state.sqlite`에 기록한다.
- 예고편 처리는 `--with-trailers`를 줄 때만 실행한다. 원본 영상과 `pipeline/data/`는 커밋하지 않는다.
- VLM 캡션 프롬프트에 인물(배우) 이름을 생성하지 말라고 명시한다.
- 검색·집계·확신도·재질문 로직에는 단위 테스트를 작성하고, pytest·ruff·`mypy --strict`가 통과해야 커밋한다. 새 의존성을 추가하면 이유를 커밋 메시지에 적는다.

## 커밋 메시지 (Conventional Commits)

`<type>(<scope>): <제목>` 형식으로 쓰고, 제목과 본문은 한국어로 쓴다. 기존 커밋 `78dd308`~`4db2ec6`은 이 규칙 이전의 `Phase N: ...` 형식이며 다시 쓰지 않는다.

| type | 언제 |
| --- | --- |
| `feat` | 새 기능 (예: 파이프라인 단계, API 엔드포인트) |
| `fix` | 버그 수정 |
| `refactor` | 동작은 같고 구조 개선 |
| `perf` | 성능(지연시간·비용) 개선 |
| `test` | 테스트만 추가·수정 |
| `ci` | GitHub Actions |
| `docs` | 문서만 (`CLAUDE.md`, `SPEC.md`, README) |
| `chore` | 의존성, 설정 등 코드 동작과 무관한 작업 |

- scope는 바뀐 영역이다: `pipeline`, `backend`, `frontend`, `eval`. 여러 영역이면 생략한다.
- 예: `feat(pipeline): s04 VLM 캡션 생성`, `fix(backend): SSE 재개 시 세션 누락 수정`
- 본문에는 무엇을 왜 바꿨는지, SPEC과 다르게 정한 것과 그 이유, 새 의존성과 추가 이유를 적는다.
- 한 커밋이 여러 종류에 걸치면 주된 변경의 type을 쓴다. 기능과 함께 쓴 테스트는 `feat`에 포함한다.
