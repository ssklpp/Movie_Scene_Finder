# 데모 시드 이미지: 파이프라인(s01~s08)을 사용자 키로 작게 돌려 빈 DB를 채운다(pipeline/seed.py).
# uv workspace라 빌드 컨텍스트는 저장소 루트다. 무시 목록은 pipeline/Dockerfile.dockerignore.
#   docker compose --profile demo up   (make demo)

FROM python:3.12-slim AS build
COPY --from=ghcr.io/astral-sh/uv:0.12.23 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_NO_DEV=1 \
    UV_NO_CACHE=1 \
    UV_PYTHON_DOWNLOADS=never
WORKDIR /app
COPY pyproject.toml uv.lock ./
COPY backend/pyproject.toml backend/pyproject.toml
RUN uv sync --frozen --no-install-workspace
COPY backend backend
COPY pipeline pipeline
RUN uv sync --frozen

FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 \
    PATH=/app/.venv/bin:$PATH
WORKDIR /app
COPY --from=build /app /app
# 수집 이미지·벡터·진행 상태(state.sqlite)는 볼륨에 둬서 실패해도 이어서 처리한다
VOLUME /app/pipeline/data
CMD ["python", "-m", "pipeline.seed"]
