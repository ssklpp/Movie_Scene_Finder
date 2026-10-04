from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app.api import routes_feedback, routes_movies, routes_search
from app.core.logging import setup_logging

setup_logging()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # 서버가 뜰 때 Postgres 체크포인터(연결 풀)와 그래프를 한 번 만든다.
    from app.agent.checkpoint import pooled_checkpointer
    from app.agent.runtime import AgentRuntime, SqlSessionStore

    saver, pool = pooled_checkpointer()
    app.state.runtime = AgentRuntime(saver, SqlSessionStore())
    try:
        yield
    finally:
        pool.close()


app = FastAPI(title="Movie Scene Finder", lifespan=lifespan)
app.state.limiter = routes_search.limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)  # type: ignore[arg-type]
app.include_router(routes_search.router)
app.include_router(routes_feedback.router)
app.include_router(routes_movies.router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
