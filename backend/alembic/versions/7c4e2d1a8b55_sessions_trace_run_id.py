"""sessions: LangSmith 트레이스 run ID

Revision ID: 7c4e2d1a8b55
Revises: 3f1c2a7b9d40
Create Date: 2026-10-18 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "7c4e2d1a8b55"
down_revision: str | None = "3f1c2a7b9d40"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("sessions", sa.Column("trace_run_id", postgresql.UUID(), nullable=True))


def downgrade() -> None:
    op.drop_column("sessions", "trace_run_id")
