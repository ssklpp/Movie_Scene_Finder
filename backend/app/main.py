from fastapi import FastAPI

from app.core.logging import setup_logging

setup_logging()

app = FastAPI(title="Movie Scene Finder")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
