"""add translation_run telemetry fields

Revision ID: a1f9d2b4c6e7
Revises: f4a8d34c1b72
Create Date: 2026-03-01 18:10:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "a1f9d2b4c6e7"
down_revision: Union[str, Sequence[str], None] = "f4a8d34c1b72"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("translation_run", sa.Column("started_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("translation_run", sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("translation_run", sa.Column("provider", sa.String(length=64), nullable=True))
    op.add_column("translation_run", sa.Column("model", sa.String(length=128), nullable=True))
    op.add_column(
        "translation_run",
        sa.Column("total_sentences", sa.BigInteger(), nullable=False, server_default=sa.text("0")),
    )
    op.add_column(
        "translation_run",
        sa.Column("processed_sentences", sa.BigInteger(), nullable=False, server_default=sa.text("0")),
    )
    op.add_column(
        "translation_run",
        sa.Column("valid_count", sa.BigInteger(), nullable=False, server_default=sa.text("0")),
    )
    op.add_column(
        "translation_run",
        sa.Column("invalid_count", sa.BigInteger(), nullable=False, server_default=sa.text("0")),
    )
    op.add_column(
        "translation_run",
        sa.Column("retries_total", sa.BigInteger(), nullable=False, server_default=sa.text("0")),
    )
    op.add_column("translation_run", sa.Column("token_prompt_total", sa.BigInteger(), nullable=True))
    op.add_column("translation_run", sa.Column("token_completion_total", sa.BigInteger(), nullable=True))
    op.add_column("translation_run", sa.Column("token_total", sa.BigInteger(), nullable=True))
    op.add_column("translation_run", sa.Column("aborted_reason", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("translation_run", "aborted_reason")
    op.drop_column("translation_run", "token_total")
    op.drop_column("translation_run", "token_completion_total")
    op.drop_column("translation_run", "token_prompt_total")
    op.drop_column("translation_run", "retries_total")
    op.drop_column("translation_run", "invalid_count")
    op.drop_column("translation_run", "valid_count")
    op.drop_column("translation_run", "processed_sentences")
    op.drop_column("translation_run", "total_sentences")
    op.drop_column("translation_run", "model")
    op.drop_column("translation_run", "provider")
    op.drop_column("translation_run", "finished_at")
    op.drop_column("translation_run", "started_at")
