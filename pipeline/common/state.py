"""파이프라인 진행 상태 (`pipeline/data/state.sqlite`).

재실행 시 이미 처리한 항목(step + item_id + model_version)을 건너뛴다 (SPEC §0.5).
"""

import sqlite3
from pathlib import Path

from app.core.config import REPO_ROOT

DEFAULT_PATH = REPO_ROOT / "pipeline" / "data" / "state.sqlite"


class State:
    def __init__(self, path: Path = DEFAULT_PATH) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(path)
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS done ("
            " step TEXT, item_id TEXT, model_version TEXT,"
            " done_at TEXT DEFAULT CURRENT_TIMESTAMP,"
            " PRIMARY KEY (step, item_id, model_version))"
        )
        self._conn.commit()

    def is_done(self, step: str, item_id: str, model_version: str = "") -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM done WHERE step = ? AND item_id = ? AND model_version = ?",
            (step, item_id, model_version),
        ).fetchone()
        return row is not None

    def mark_done(self, step: str, item_id: str, model_version: str = "") -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO done (step, item_id, model_version) VALUES (?, ?, ?)",
            (step, item_id, model_version),
        )
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()
