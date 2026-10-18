.PHONY: up down migrate test dev index eval lint demo demo-down

LIMIT ?=
LIMIT_ARG := $(if $(LIMIT),--limit $(LIMIT),)
EVAL_CONFIG ?= eval/configs/E1_hybrid.yaml
SPLIT ?= dev

up:
	docker compose up -d --wait

down:
	docker compose down

# .env의 OpenAI·TMDB 키로 영화 SEED_LIMIT편(기본 20)을 색인하고 backend(:8000)·frontend(:3000)를 띄운다.
# 처음 한 번은 수 분 걸리고, 이미 색인돼 있으면 seed는 바로 끝난다.
demo:
	docker compose --profile demo up -d --build --wait

demo-down:
	docker compose --profile demo down

migrate:
	cd backend && uv run alembic upgrade head

test:
	uv run pytest

lint:
	uv run ruff check . && uv run ruff format --check . && uv run mypy backend pipeline

dev:
	trap 'kill 0' EXIT; \
	uv run uvicorn app.main:app --reload --port 8000 --app-dir backend & \
	pnpm -C frontend dev --port 3000 & \
	wait

# build_user_dict는 s07(sparse 토큰화)보다 먼저 돌아야 한다.
index:
	for s in s01_collect_meta s02_collect_images s03_dedup build_user_dict s04_caption \
	         s05_validate s06_build_docs s07_embed s08_upload; do \
		uv run python -m pipeline.$$s $(LIMIT_ARG) || exit 1; \
	done

eval:
	uv run python -m eval.run_eval --config $(EVAL_CONFIG) --split $(SPLIT)
