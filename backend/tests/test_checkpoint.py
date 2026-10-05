from typing import Any

import pytest
from psycopg_pool import ConnectionPool

from app.agent import checkpoint


def test_pooled_checkpointer_checks_connections(monkeypatch: pytest.MonkeyPatch) -> None:
    """DB가 재시작된 뒤 끊긴 연결을 빌려주지 않도록 풀이 연결을 확인해야 한다."""
    captured: dict[str, Any] = {}

    class FakePool:
        check_connection = ConnectionPool.check_connection

        def __init__(self, conninfo: str, **kwargs: Any) -> None:
            captured.update(kwargs)

    class FakeSaver:
        def __init__(self, conn: Any, serde: Any) -> None: ...

        def setup(self) -> None: ...

    monkeypatch.setattr(checkpoint, "ConnectionPool", FakePool)
    monkeypatch.setattr(checkpoint, "PostgresSaver", FakeSaver)
    checkpoint.pooled_checkpointer()
    assert captured["check"] is ConnectionPool.check_connection
