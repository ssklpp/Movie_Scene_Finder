# 보강 계획: 원클릭 실행 · 피드백-트레이스 연결

작성일 2026-10-16 · 상태: 1·2 완료(2026-10-18). 1은 TMDB 약관 때문에 "샘플 데이터 배포"에서 "사용자 키로 시드 생성"으로 바꿨다

Movie Scene Finder는 관측(LangSmith), 평가(Recall·MRR·p95·비용, `/eval` 대시보드), Postgres 체크포인터, `clarify` 노드의 `interrupt`/`Command(resume=…)`가 이미 갖춰져 있다. 그래서 이 저장소에는 두 가지만 추가한다.

1. Docker Compose 원클릭 실행(사용자 키로 시드 생성)
2. 사용자 피드백을 LangSmith 트레이스에 연결

MCP 서버, 승인형 HITL, 자동화는 영화 챗봇(IMDb_Top250) 저장소에서 진행한다. 이 저장소는 검색 품질·평가를 대표하는 프로젝트로 유지하고 범위를 넓히지 않는다.

## 현재 상태 (2026-10-16 `main` 기준)

| 항목 | 상태 |
| --- | --- |
| 관측 | LangSmith, 사용자 사진 가림, 세션별 지연·비용 DB 저장 |
| 평가 | 실험 config 30여 개, `eval_runs` 테이블, `/eval` 대시보드 |
| 체크포인트 | `PostgresSaver`, `thread_id = session_id` |
| HITL | `clarify` 노드 `interrupt` → `Command(resume=…)` |
| Docker | `backend/Dockerfile` 있음. `docker-compose.yml`은 Qdrant·Postgres만 띄움. frontend Dockerfile 없음 |
| 데이터 | compose로 띄우면 Qdrant·Postgres가 비어 있음. 채우려면 `make index` 8단계 파이프라인(TMDB 토큰, 이미지 수집, VLM 캡셔닝) 필요 |

---

## 1. 원클릭 실행 (사용자 키로 시드 생성)

처음 계획은 샘플 카탈로그·Qdrant 스냅샷을 GitHub Release에 올리고 복원하는 것이었으나, **TMDB 약관 확인 결과 바꿨다**(2026-10-18, 사용자 결정).

- [TMDB API 약관](https://www.themoviedb.org/api-terms-of-use)(2023-10-20 개정) §1.C는 TMDB 콘텐츠의 2차 저작물 작성, 서브라이선스, 6개월 넘는 캐시, ML·AI 애플리케이션 사용을 금지하고, §2.A는 캐시한 데이터셋을 다른 사람에게 제공하는 것을 예로 든다. 시드에는 제목·줄거리와 TMDB 이미지로 만든 캡션·벡터가 들어가므로, "줄거리를 빼고 캡션·벡터·제목만"으로 줄여도 해당된다.
- KMDb Open API는 "OPEN 공공누리 공공제작품 자유이용허락" 표시가 있지만, TMDB가 막히면 KMDb만으로는 시드를 만들 수 없다.

그래서 데이터를 배포하지 않고, `seed` 컨테이너가 **사용자 자신의 TMDB·OpenAI 키로 파이프라인을 작게 돌린다**. 목표는 "키 두 개 넣고 `make demo`"다.

### 서비스 구성 (`docker compose --profile demo`, `make demo`)

| 서비스 | 내용 |
| --- | --- |
| `qdrant`, `postgres` | 지금과 같음. 프로필이 없어 `make up`(개발)은 그대로 둘만 띄운다 |
| `seed` | `pipeline/Dockerfile`, `python -m pipeline.seed --limit $SEED_LIMIT`(기본 20). 한 번 실행되고 끝난다 |
| `backend` | 기존 `backend/Dockerfile`. `seed`가 성공한 뒤 뜬다, `/health` 헬스체크 |
| `frontend` | 새 `frontend/Dockerfile`(Next.js standalone, `NEXT_OUTPUT=standalone`일 때만. Vercel 빌드는 그대로) |

### 시드 동작 (`pipeline/seed.py`)

1. 장면 alias(`scenes`)가 이미 있으면 바로 끝난다. s08이 마지막에 alias를 걸기 때문에, 중간에 실패한 시드는 다음 실행에서 이어서 처리한다(각 단계가 `state.sqlite`로 멱등, `pipeline/data`는 볼륨).
2. 없으면 `alembic upgrade head` → s01~s08을 `--limit`으로 순서대로 돌린다.
3. `build_user_dict`는 돌리지 않는다. backend 이미지에 든 저장소의 사전을 s07도 그대로 써야 인덱싱과 질의의 토큰화가 같다.

### 운영 데이터 보호

demo 컨테이너는 `.env`를 읽되 compose가 `DATABASE_URL`·`QDRANT_URL`을 compose 안의 컨테이너로 고정하고, `QDRANT_API_KEY`·R2 키·`R2_PUBLIC_URL`을 비우고, `LANGSMITH_TRACING=false`로 둔다. 프로젝트 `.env`의 `QDRANT_URL`이 Qdrant Cloud(운영)이고 R2 키도 있어서, 덮어쓰지 않으면 s08이 운영 alias와 R2 버킷을 바꾼다.

### 처음 계획에서 빠진 것

- 스냅샷·manifest·체크섬과 "설정과 시드의 임베딩 차원 비교"는 필요 없다. 같은 설정으로 그 자리에서 만들기 때문이다.
- Qdrant 버전 고정도 스냅샷 호환 때문이었으므로 하지 않는다.

### 완료 기준

- [x] 새 볼륨(새 clone과 같은 상태)에서 OpenAI·TMDB 키만 넣고 `make demo` 후 장면 검색이 된다
- [x] 두 번째 실행에서는 `seed`가 색인을 건너뛴다
- [x] 프로젝트 `.env`가 운영 Qdrant·R2를 가리켜도 demo가 운영 데이터를 건드리지 않는다
- [x] README 빠른 시작에 uv·Node 없이 실행하는 경로가 추가된다

확인(2026-10-18, 별도 compose 프로젝트 `-p msfdemotest`로 빈 볼륨에서 `--profile demo up -d --build --wait`):

- seed 약 5분 30초: 영화 20편, 장면 269(캡션 실패 0, $0.078), alias `scenes` → `scenes_v1`. backend healthy.
- 검색: "마법 학교로 가는 기차를 타려고 벽으로 뛰어드는 장면" → 1위 해리 포터와 마법사의 돌(0.99), "부잣집 지하실에 몰래 숨어 사는 남자" → 1위 기생충(1.0). 썸네일은 R2가 꺼져 있어 null.
- frontend: 3000번을 다른 프로젝트 컨테이너가 쓰고 있어 compose로는 뜨지 못했고, 같은 이미지를 3001번으로 띄워 페이지와 번들의 API 주소(`localhost:8000`)를 확인했다. 브라우저 화면 확인은 하지 않았다.
- 두 번째 실행: "alias exists; seed skipped", 3초.
- seed 로그의 Qdrant 주소는 `http://qdrant:6333`뿐이고 R2 업로드는 건너뜀. Qdrant Cloud alias는 그대로 `scenes → scenes_v3`.

---

## 2. 피드백 → 트레이스 연결

지금은 결과 화면의 정답/오답 피드백이 `feedback` 테이블에만 쌓이고, LangSmith 트레이스는 `session_id` 메타데이터로만 묶여 있다. 둘을 이으면 "사용자가 틀렸다고 한 검색"을 트레이스에서 바로 열어 원인을 볼 수 있다.

1. `agent/runtime.py`의 `_run`이 요청마다 루트 run ID를 직접 만들어 그래프 config(`run_id`)에 넘긴다. 트레이스는 세션 하나가 아니라 **요청마다 하나**(`search`, 재질문 답마다 `answer`)이므로, `result` 이벤트를 낸 요청의 run ID로 `sessions.trace_run_id` 컬럼(alembic 마이그레이션)을 덮어쓴다. 첫 `search`의 ID를 저장하면 재질문이 있었던 세션의 피드백이 결과를 만들지 않은 트레이스에 붙는다.
2. `POST /feedback`에서 DB 저장 후 백그라운드 작업으로 LangSmith `create_feedback(run_id, key="user_correct", score=1|0)`을 보낸다. 추적이 꺼져 있으면 건너뛴다. 응답 속도와 LangSmith 장애가 사용자에게 영향을 주지 않게 하기 위해서다.
3. LangSmith에서 `user_correct = 0`인 run을 모아 원인을 보고, SPEC §11의 regression 데이터셋(`feedback.is_correct = false` 세션 누적)을 만들 때 트레이스 링크를 함께 남긴다. regression은 아직 만들어지지 않은 데이터셋이라, 이 작업이 그 첫 수집 경로가 된다.

운영 → 실패 수집 → 평가셋 → 개선 → 재평가로 이어지는 루프가 완성된다.

### 평가 지표 추가

- 운영 중 정답 피드백 비율(온라인 정확도)을 오프라인 Recall@1과 나란히 기록한다. 두 값의 차이는 평가셋이 실제 사용자 질의를 얼마나 대표하는지 보여 준다.
- 피드백 표본이 적을 때는 비율과 함께 건수를 적는다.

### 완료 기준

- [x] 오답 피드백을 누른 검색이 LangSmith에서 `user_correct = 0`으로 보인다 (2026-10-18 배포 서버: "기차 안에서 좀비들이 뛰어오는 장면" → 1위 부산행, 2위 설국열차에 오답 피드백 → 운영 프로젝트 `search` 트레이스에 `user_correct = 0`, comment `movie_id=43`)
- [x] 재질문 2회 세션의 피드백이 결과를 낸 마지막 `answer` 트레이스에 붙는다 (`test_trace_run_id_is_from_request_that_produced_result`, 재질문 1회 세션으로 확인)
- [x] 추적이 꺼진 환경에서도 `/feedback`이 지금처럼 204를 돌려준다
- [x] 피드백 전송 실패가 API 응답에 영향을 주지 않는다는 단위 테스트가 있다 (`test_send_feedback_failure_is_swallowed`, `test_feedback_sent_to_trace_and_failure_keeps_204`)

"평가 지표 추가"(온라인 정확도)는 피드백이 쌓인 뒤에 한다.

---

## 일정과 위험 요소

영화 챗봇 쪽 작업(2026-10-22 ~ 11-14)을 먼저 끝내고, 2026-11-15 ~ 11-18에 진행한다. 다른 작업과 의존 관계가 없어 일정이 밀리면 뒤로 미룬다.

| 위험 | 대응 |
| --- | --- |
| TMDB·KMDb 재배포 불가 | **실제로 해당**(TMDB 약관 §1.C·§2.A). 데이터를 배포하지 않고 사용자 키로 시드 생성 |
| 피드백이 엉뚱한 트레이스에 붙음 | 결과를 낸 요청의 run ID로 `trace_run_id` 덮어쓰기, 재질문 세션 테스트 |
| demo가 운영 Qdrant·R2를 건드림 | compose가 저장소 주소를 compose 안으로 고정, R2 키를 비움 |
| 포트 충돌(3000·8000·5432·6333) | 다른 프로젝트 컨테이너가 쓰고 있으면 그 서비스만 뜨지 않는다. README에 안내 |

일정은 계획(11-15 ~ 11-18)보다 당겨 2026-10-18에 두 항목 모두 진행했다.
