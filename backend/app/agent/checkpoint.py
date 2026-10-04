"""체크포인터 (SPEC §8.2: PostgresSaver, thread_id = session_id)."""

from collections.abc import Iterator
from contextlib import contextmanager

from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from psycopg import Connection
from psycopg.rows import DictRow, dict_row
from psycopg_pool import ConnectionPool

from app.agent.state import STATE_MODELS
from app.core.config import get_settings


def make_serde() -> JsonPlusSerializer:
    """상태의 pydantic 모델만 복원을 허용하는 직렬화기."""
    return JsonPlusSerializer(
        allowed_msgpack_modules=[(m.__module__, m.__name__) for m in STATE_MODELS]
    )


def psycopg_url(sqlalchemy_url: str) -> str:
    """SQLAlchemy URL(postgresql+psycopg://)을 psycopg가 받는 형식(postgresql://)으로."""
    return sqlalchemy_url.replace("postgresql+psycopg://", "postgresql://", 1)


def pooled_checkpointer() -> tuple[PostgresSaver, ConnectionPool[Connection[DictRow]]]:
    """API 서버용: 동시 요청을 위해 연결 풀을 쓴다. 풀은 호출한 쪽이 닫는다."""
    pool: ConnectionPool[Connection[DictRow]] = ConnectionPool(
        psycopg_url(get_settings().database_url),
        kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row},
        max_size=10,
        open=True,
    )
    saver = PostgresSaver(pool, serde=make_serde())
    saver.setup()
    return saver, pool


@contextmanager
def postgres_checkpointer(setup: bool = True) -> Iterator[PostgresSaver]:
    """Postgres 체크포인터. 처음 쓸 때 setup()이 체크포인트 테이블을 만든다."""
    url = psycopg_url(get_settings().database_url)
    conn: Connection[DictRow] = Connection.connect(
        url, autocommit=True, prepare_threshold=0, row_factory=dict_row
    )
    try:
        saver = PostgresSaver(conn, serde=make_serde())
        if setup:
            saver.setup()
        yield saver
    finally:
        conn.close()
