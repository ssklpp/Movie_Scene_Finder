# 검색 API(backend) 이미지. uv workspace라 빌드 컨텍스트는 저장소 루트다.
#   docker build -f backend/Dockerfile -t msf-backend .
# 실행 시 DB 스키마를 최신으로 맞춘 뒤(alembic upgrade head) 서버를 띄운다. 설정은 모두 환경 변수로 받는다.

# 1단계: 의존성 설치. uv와 다운로드 캐시는 최종 이미지에 남기지 않는다.
FROM python:3.12-slim AS build
COPY --from=ghcr.io/astral-sh/uv:0.12.23 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_NO_DEV=1 \
    UV_NO_CACHE=1 \
    UV_PYTHON_DOWNLOADS=never
WORKDIR /app
# 의존성만 먼저 설치해 코드가 바뀌어도 이 층을 재사용한다. backend에 필요한 것만 설치한다.
COPY pyproject.toml uv.lock ./
COPY backend/pyproject.toml backend/pyproject.toml
RUN uv sync --frozen --package msf-backend --no-install-workspace
COPY backend backend
RUN uv sync --frozen --package msf-backend

# 2단계: 실행 이미지. 가상환경과 코드만 가져온다.
FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 \
    PATH=/app/.venv/bin:$PATH
WORKDIR /app
COPY --from=build /app/.venv /app/.venv
COPY --from=build /app/backend /app/backend
EXPOSE 8000

# Railway는 PORT를 정해 준다. 로컬에서는 8000.
# 요청은 플랫폼 프록시를 거쳐 들어오므로 X-Forwarded-For의 실제 접속 IP를 쓴다
# (없으면 IP당 rate limit이 모든 사용자를 프록시 IP 하나로 묶는다).
CMD ["sh", "-c", "cd backend && alembic upgrade head && exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips='*'"]
