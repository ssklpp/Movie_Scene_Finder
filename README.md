# Movie Scene Finder (장면 기억 검색기)

기억나는 영화 장면을 글이나 사진으로 설명하면 어떤 영화인지 찾아 주는 검색 서비스입니다.

> **개발 중입니다.** 지금은 Phase 2(캡셔닝과 Qdrant 적재)까지 구현되어 있고, 검색 API와 화면은 아직 없습니다.
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
| 3 | 하이브리드 검색, 첫 평가 | 다음 단계 |
| 4 | LangGraph 에이전트(재질문), API | 예정 |
| 5 | 프론트엔드, 배포 | 예정 |
| 6 | 실험, 문서화 | 예정 |

지금까지 만든 데이터: 영화 300편(한국 영화 약 60편 포함), 이미지 4,446장, 중복을 걸러 낸 장면 3,852개와
장면마다의 한국어 캡션(`gpt-6-luna`, 검증 실패 0.18%), Qdrant 색인(장면 3,852개, 줄거리 299편),
사람이 직접 쓴 평가 질의 20개([작성 안내](eval/human_guide.md)).

## 기술 스택

- **Backend**: Python 3.12, FastAPI, SQLAlchemy + Alembic, PostgreSQL 16
- **Search**: Qdrant(dense + sparse), OpenAI 임베딩, Kiwi 형태소 분석(kiwipiepy)
- **Agent**: LangGraph (예정)
- **VLM 캡셔닝**: `gpt-6-luna`. 로컬 Qwen3-VL-4B(AWQ 4비트, vLLM)와 비교해 결정
- **Frontend**: Next.js, TypeScript, Tailwind (예정)
- **Tooling**: uv, pnpm, ruff, mypy `--strict`, pytest, GitHub Actions

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
uv run python -m pipeline.s08_upload            # Qdrant 적재, 별칭 scenes 교체
```

- 대부분의 단계에 `--limit N`(앞 N편만 처리)과 `--force`(이미 처리한 것도 다시)를 줄 수 있습니다.
- 다시 실행하면 처리한 항목은 건너뜁니다. 진행 상태는 `pipeline/data/state.sqlite`에 남습니다.
- 수집한 이미지와 중간 결과(`pipeline/data/`)는 저장소에 올리지 않습니다.

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
eval/       평가 데이터셋(human 질의 20개)과 실험 설정
scripts/    로컬 VLM(vLLM) 실행 스크립트
frontend/   Next.js 앱 (예정)
SPEC.md     구현 명세
```

## 데이터 출처

영화 정보와 이미지는 [TMDB](https://www.themoviedb.org/)에서 가져옵니다.

This product uses the TMDB API but is not endorsed or certified by TMDB.
