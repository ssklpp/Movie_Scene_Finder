"""PostgreSQL 스키마 (SPEC §5.1). LangGraph 체크포인트 테이블은 PostgresSaver.setup()이 만든다."""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    ARRAY,
    REAL,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Movie(Base):
    __tablename__ = "movies"

    id: Mapped[int] = mapped_column(primary_key=True)
    tmdb_id: Mapped[int] = mapped_column(unique=True)
    title_ko: Mapped[str | None] = mapped_column(Text)
    title_en: Mapped[str | None] = mapped_column(Text)
    year: Mapped[int | None]
    country: Mapped[str | None] = mapped_column(Text)
    genres: Mapped[list[str] | None] = mapped_column(ARRAY(Text))
    is_animation: Mapped[bool | None]
    plot_ko: Mapped[str | None] = mapped_column(Text)
    poster_url: Mapped[str | None] = mapped_column(Text)


class Scene(Base):
    __tablename__ = "scenes"
    __table_args__ = (
        CheckConstraint("source IN ('backdrop','still','trailer')", name="scenes_source_check"),
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True)  # f"{tmdb_id}_{source}_{n}"
    movie_id: Mapped[int] = mapped_column(ForeignKey("movies.id"))
    source: Mapped[str] = mapped_column(Text)
    r2_key: Mapped[str | None] = mapped_column(Text)
    phash: Mapped[str | None] = mapped_column(Text)
    caption_ko: Mapped[str | None] = mapped_column(Text)
    caption_en: Mapped[str | None] = mapped_column(Text)
    tags: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    model_version: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Session(Base):
    __tablename__ = "sessions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    query_text: Mapped[str | None] = mapped_column(Text)
    image_key: Mapped[str | None] = mapped_column(Text)
    rewritten: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    hard_filters: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    clarify_turns: Mapped[int | None]
    result_movie_ids: Mapped[list[int] | None] = mapped_column(ARRAY(Integer))
    confidence: Mapped[float | None] = mapped_column(REAL)
    latency_ms: Mapped[int | None]
    cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(10, 6))


class Feedback(Base):
    __tablename__ = "feedback"

    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sessions.id"))
    movie_id: Mapped[int] = mapped_column(ForeignKey("movies.id"))
    is_correct: Mapped[bool]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class EvalRun(Base):
    __tablename__ = "eval_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    dataset_version: Mapped[str | None] = mapped_column(Text)
    split: Mapped[str | None] = mapped_column(Text)
    config: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    recall_at_1: Mapped[float | None] = mapped_column(REAL)
    recall_at_5: Mapped[float | None] = mapped_column(REAL)
    mrr: Mapped[float | None] = mapped_column(REAL)
    clarify_success: Mapped[float | None] = mapped_column(REAL)
    avg_clarify: Mapped[float | None] = mapped_column(REAL)
    p95_latency_ms: Mapped[int | None]
    cost_per_query_usd: Mapped[float | None] = mapped_column(REAL)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
