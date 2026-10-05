#!/usr/bin/env bash
# 로컬 DB의 평가 기록(eval_runs)을 배포 DB로 복사한다. 배포된 /eval 대시보드가 이 표를 읽는다.
#
#   scripts/copy_eval_runs.sh "postgresql://USER:PASS@HOST:PORT/DB"
#
# 평가는 로컬에서만 돌리므로 배포 DB의 eval_runs는 매번 비우고 로컬 것으로 바꾼다(run id 유지).
# 접속 방법은 copy_catalog.sh와 같다(Railway Postgres Public Access를 잠깐 켜고 끈다).
set -euo pipefail
TARGET="${1:?usage: copy_eval_runs.sh TARGET_DATABASE_URL}"
TARGET="${TARGET/postgresql+psycopg:\/\//postgresql://}"
cd "$(dirname "$0")/.."

masked=$(echo "$TARGET" | sed -E 's#//[^@]*@#//***@#')
psql_target() { docker compose exec -T postgres psql "$TARGET" -v ON_ERROR_STOP=1 -qtA "$@"; }

echo "copying eval_runs -> $masked"
psql_target -c "TRUNCATE eval_runs RESTART IDENTITY"
docker compose exec -T postgres pg_dump -U app -d msf --data-only --table=eval_runs \
  | docker compose exec -T postgres psql "$TARGET" -v ON_ERROR_STOP=1 -q
psql_target -c "SELECT 'eval_runs', count(*) FROM eval_runs"
