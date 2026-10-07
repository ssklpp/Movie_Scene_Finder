"""movies: KMDb 보강 컬럼

Revision ID: 3f1c2a7b9d40
Revises: e82a0857021c
Create Date: 2026-10-07 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "3f1c2a7b9d40"
down_revision: str | None = "e82a0857021c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("movies", sa.Column("kmdb_id", sa.Text(), nullable=True))
    op.add_column("movies", sa.Column("plot_kmdb", sa.Text(), nullable=True))
    op.add_column("movies", sa.Column("keywords_ko", postgresql.ARRAY(sa.Text()), nullable=True))


def downgrade() -> None:
    op.drop_column("movies", "keywords_ko")
    op.drop_column("movies", "plot_kmdb")
    op.drop_column("movies", "kmdb_id")
