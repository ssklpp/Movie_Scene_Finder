.PHONY: up down migrate test dev index eval lint

LIMIT ?=
LIMIT_ARG := $(if $(LIMIT),--limit $(LIMIT),)
EVAL_CONFIG ?= eval/configs/E1_hybrid.yaml
SPLIT ?= dev

up:
	docker compose up -d --wait

down:
	docker compose down

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

index:
	for s in s01_collect_meta s02_collect_images s03_dedup s04_caption \
	         s05_validate s06_build_docs s07_embed s08_upload; do \
		uv run python -m pipeline.$$s $(LIMIT_ARG) || exit 1; \
	done

eval:
	uv run python -m eval.run_eval --config $(EVAL_CONFIG) --split $(SPLIT)
