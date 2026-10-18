"""데모 시드: 빈 Qdrant·Postgres를 사용자 키(TMDB, OpenAI)로 영화 몇 편만 색인해 채운다.

`docker compose --profile demo up`의 `seed` 서비스가 한 번 실행한다(`make demo`).
TMDB 약관(2차 저작물·데이터셋 제공 금지)상 미리 만든 카탈로그·캡션·벡터를 배포할 수 없어,
각자 자기 키로 파이프라인을 작게 돌린다.

- 장면 alias(`QDRANT_SCENES_ALIAS`)가 이미 있으면 아무것도 하지 않는다. s08이 마지막에 alias를
  걸기 때문에, 중간에 실패한 시드는 다음 실행에서 이어서 처리한다(각 단계가 멱등).
- `build_user_dict`는 돌리지 않는다. backend 이미지에 든 저장소의 사전을 s07도 그대로 써야
  인덱싱과 질의의 토큰화가 같다.
"""

import argparse
import logging
import subprocess
import sys

from qdrant_client import QdrantClient

from app.core.config import REPO_ROOT, get_settings
from app.core.logging import setup_logging
from app.search.qdrant import get_qdrant

logger = logging.getLogger(__name__)

STEPS = [
    "s01_collect_meta",
    "s02_collect_images",
    "s03_dedup",
    "s04_caption",
    "s05_validate",
    "s06_build_docs",
    "s07_embed",
    "s08_upload",
]
DEFAULT_LIMIT = 20


def already_seeded(client: QdrantClient, alias: str) -> bool:
    return alias in {a.alias_name for a in client.get_aliases().aliases}


def commands(limit: int) -> list[list[str]]:
    migrate = [sys.executable, "-m", "alembic", "upgrade", "head"]
    steps = [[sys.executable, "-m", f"pipeline.{s}", "--limit", str(limit)] for s in STEPS]
    return [migrate, *steps]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT, help="색인할 영화 수")
    args = parser.parse_args()
    setup_logging()
    alias = get_settings().qdrant_scenes_alias
    if already_seeded(get_qdrant(), alias):
        logger.info("Qdrant alias %r exists; seed skipped", alias)
        return
    logger.info("seeding %d movies (takes several minutes)", args.limit)
    for cmd in commands(args.limit):
        logger.info("run: %s", " ".join(cmd[1:]))
        # alembic은 backend/alembic.ini를 읽으므로 backend에서 돌린다
        cwd = REPO_ROOT / "backend" if "alembic" in cmd else REPO_ROOT
        if subprocess.run(cmd, cwd=cwd).returncode != 0:
            sys.exit(f"seed failed at: {' '.join(cmd[1:])}")
    logger.info("seed done")


if __name__ == "__main__":
    main()
