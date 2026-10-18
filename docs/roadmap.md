# 보강 계획: 원클릭 실행 · 피드백-트레이스 연결

작성일 2026-10-16 · 상태: 1은 계획, 2는 구현(2026-10-18, 배포 확인 전)

Movie Scene Finder는 관측(LangSmith), 평가(Recall·MRR·p95·비용, `/eval` 대시보드), Postgres 체크포인터, `clarify` 노드의 `interrupt`/`Command(resume=…)`가 이미 갖춰져 있다. 그래서 이 저장소에는 두 가지만 추가한다.

1. 샘플 시드 기반 Docker Compose 원클릭 실행
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

## 1. 샘플 시드 기반 원클릭 실행

이 저장소의 원클릭 실행은 컨테이너보다 **데이터가 관문**이다. 샘플 데이터를 미리 만들어 두고, 처음 뜰 때 자동으로 복원한다. 목표는 "OpenAI 키 하나 넣고 `docker compose up`"이다. 질의 임베딩과 재작성에 OpenAI가 쓰이므로 키는 계속 필요하다.

### 서비스 구성

| 서비스 | 내용 |
| --- | --- |
| `qdrant` | `qdrant/qdrant:latest` 대신 버전 고정. 스냅샷은 버전 사이 호환이 보장되지 않는다 |
| `postgres` | 지금과 같음 |
| `seed` | 한 번 실행되고 끝나는 init 컨테이너. `movies`가 비어 있을 때만 복원 |
| `backend` | 기존 `backend/Dockerfile` (시작할 때 `alembic upgrade head`) |
| `frontend` | 새 `frontend/Dockerfile` (Next.js standalone) |

### 시드 만들기와 복원

1. 300편 중 50편 안팎을 골라 샘플 카탈로그를 만든다. `scripts/copy_catalog.sh`의 `pg_dump --data-only --table=movies --table=scenes` 방식을 영화 ID 조건으로 좁힌다.
2. Qdrant의 장면·줄거리 컬렉션 스냅샷을 만든다. 샘플만 남긴 컬렉션을 따로 만들어 스냅샷을 뜨는 편이 간단하다. **반드시 로컬 Qdrant에서 만든다.** 프로젝트 `.env`의 `QDRANT_URL`은 Qdrant Cloud(배포)를 가리키므로, 그대로 s08이나 컬렉션 작업을 돌리면 운영 alias가 바뀐다.
3. 둘을 하나의 압축 파일로 묶고 `manifest.json`에 임베딩 모델(`text-embedding-3-small`), 차원(1536), 캡션 모델 버전, 영화 수, SHA-256을 적는다. GitHub Release에 올려 저장소 크기는 늘리지 않는다.
4. `seed` 컨테이너는 `movies`가 비어 있을 때만 파일을 받아 체크섬을 확인하고, `psql`로 카탈로그를, Qdrant REST 스냅샷 업로드로 컬렉션을 복원한다. 마지막에 `QDRANT_SCENES_ALIAS`(`scenes`) 별칭을 다시 건다. 스냅샷에는 별칭이 포함되지 않는다.
5. `backend`는 `depends_on: seed: condition: service_completed_successfully`로 시드 이후에 뜬다.

### 대안: 스냅샷 대신 벡터 parquet + s08 (구현 때 정한다)

Qdrant 스냅샷 대신 샘플 영화만 남긴 s07 출력(`pipeline/data/vectors/{scenes,movies}.parquet`)을 시드에 넣고, `seed` 컨테이너가 s08로 적재하는 방법도 있다.

| | 스냅샷 복원 | parquet + s08 |
| --- | --- | --- |
| Qdrant 버전 호환 | 버전 고정 필요, 올리면 시드를 다시 만든다 | 상관없음 (upsert로 적재) |
| alias | 복원 후 직접 다시 건다 | s08이 기존 코드대로 `scenes_v{n}` 생성 → alias 교체 |
| `seed` 이미지 | 작음 (`curl`·`psql`) | 큼 (pipeline 의존성 필요) |
| 시드 크기 | 비슷함 | 비슷함 |

### 주의할 점

- **이용약관 확인이 먼저다.** 시드에는 TMDB·KMDb 줄거리 텍스트와 TMDB 이미지로 만든 캡션이 들어간다. 재배포가 허용되는지 확인하고, 어렵다면 줄거리를 빼고 캡션·벡터·제목만 담는다. README의 TMDB 출처 표기는 유지한다.
- **설정과 시드가 어긋나지 않게 한다.** `.env`의 `EMBED_MODEL`·`EMBED_DIM`이 `manifest.json`과 다르면 검색이 조용히 망가진다. backend 시작 시 비교해 다르면 바로 실패시킨다.
- **썸네일은 빼도 된다.** R2 키가 없으면 캡션만 보여 주는 폴백이 이미 있다.
- **프런트 API 주소는 빌드 시점에 굳는다.** `NEXT_PUBLIC_` 변수는 빌드 때 이미지에 박히므로 compose `build.args`로 `http://localhost:8000`을 넘기고, `CORS_ORIGINS`에 `http://localhost:3000`을 둔다.
- **샘플 검색 수치는 README 결과와 다르다.** 후보가 줄면 Recall이 올라간다. README에 "데모용 샘플이며 평가 수치는 300편 기준"이라고 밝힌다.

### 완료 기준

- [ ] 새로 clone한 폴더에서 OpenAI 키만 넣고 `docker compose up --wait` 후 장면 검색이 된다
- [ ] 두 번째 실행에서는 `seed`가 복원을 건너뛴다
- [ ] 설정과 시드의 임베딩 차원이 다르면 backend가 명확한 메시지로 시작을 거부한다
- [ ] README 빠른 시작에 파이프라인 없이 실행하는 경로가 추가된다

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

- [ ] 오답 피드백을 누른 검색이 LangSmith에서 `user_correct = 0`으로 보인다 (2026-10-18: 작은 그래프로 config `run_id` = 루트 run ID, 그 run에 `user_correct = 0`이 붙는 것까지 실제 LangSmith에서 확인. 배포 서버 검색으로는 아직)
- [x] 재질문 2회 세션의 피드백이 결과를 낸 마지막 `answer` 트레이스에 붙는다 (`test_trace_run_id_is_from_request_that_produced_result`, 재질문 1회 세션으로 확인)
- [x] 추적이 꺼진 환경에서도 `/feedback`이 지금처럼 204를 돌려준다
- [x] 피드백 전송 실패가 API 응답에 영향을 주지 않는다는 단위 테스트가 있다 (`test_send_feedback_failure_is_swallowed`, `test_feedback_sent_to_trace_and_failure_keeps_204`)

"평가 지표 추가"(온라인 정확도)는 피드백이 쌓인 뒤에 한다.

---

## 일정과 위험 요소

영화 챗봇 쪽 작업(2026-10-22 ~ 11-14)을 먼저 끝내고, 2026-11-15 ~ 11-18에 진행한다. 다른 작업과 의존 관계가 없어 일정이 밀리면 뒤로 미룬다.

| 위험 | 대응 |
| --- | --- |
| TMDB·KMDb 재배포 불가 | 캡션·벡터·제목만 담은 시드로 축소 |
| 피드백이 엉뚱한 트레이스에 붙음 | 결과를 낸 요청의 run ID로 `trace_run_id` 덮어쓰기, 재질문 세션 테스트 |
| Qdrant 버전 업 후 스냅샷 복원 실패 | 이미지 버전 고정, `manifest.json`에 Qdrant 버전 기록 |
| 시드 파일 다운로드 실패 | 체크섬 불일치 시 명확한 오류로 중단, 수동 다운로드 경로를 README에 안내 |
