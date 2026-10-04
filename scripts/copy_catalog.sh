#!/usr/bin/env bash
# 로컬 DB(docker compose postgres)의 영화 카탈로그(movies, scenes)를 배포 DB로 복사한다.
# 결과 화면의 제목·연도·포스터와 근거 장면 정보가 이 두 테이블에서 나온다.
#
#   scripts/copy_catalog.sh "postgresql://USER:PASS@HOST:PORT/DB" [--replace]
#
# - 배포 DB에 스키마가 있어야 한다(backend 컨테이너가 시작할 때 alembic upgrade head를 한다).
# - 배포 DB에 이미 영화가 있으면 멈춘다. --replace를 주면 movies·scenes를 비우고 다시 넣는다
#   (movies를 참조하는 feedback도 함께 지워진다).
set -euo pipefail
TARGET="${1:?usage: copy_catalog.sh TARGET_DATABASE_URL [--replace]}"
TARGET="${TARGET/postgresql+psycopg:\/\//postgresql://}"
REPLACE="${2:-}"
cd "$(dirname "$0")/.."

masked=$(echo "$TARGET" | sed -E 's#//[^@]*@#//***@#')
psql_target() { docker compose exec -T postgres psql "$TARGET" -v ON_ERROR_STOP=1 -qtA "$@"; }

existing=$(psql_target -c "SELECT count(*) FROM movies")
if [ "$existing" != "0" ]; then
  if [ "$REPLACE" != "--replace" ]; then
    echo "target already has $existing movies ($masked). Re-run with --replace to overwrite." >&2
    exit 1
  fi
  psql_target -c "TRUNCATE movies, scenes RESTART IDENTITY CASCADE"
fi

echo "copying movies, scenes -> $masked"
docker compose exec -T postgres pg_dump -U app -d msf --data-only --table=movies --table=scenes \
  | docker compose exec -T postgres psql "$TARGET" -v ON_ERROR_STOP=1 -q
psql_target -c "SELECT 'movies', count(*) FROM movies UNION ALL SELECT 'scenes', count(*) FROM scenes"
