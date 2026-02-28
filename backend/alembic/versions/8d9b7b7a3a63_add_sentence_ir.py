"""add sentence ir

Revision ID: 8d9b7b7a3a63
Revises: 617257da99ce
Create Date: 2026-02-28 15:12:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "8d9b7b7a3a63"
down_revision: Union[str, Sequence[str], None] = "617257da99ce"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "sentence_ir",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("translation_run_id", sa.BigInteger(), nullable=False),
        sa.Column("sentence_id", sa.BigInteger(), nullable=False),
        sa.Column("ir_json", sa.JSON(), nullable=False),
        sa.Column("is_valid", sa.Boolean(), nullable=False),
        sa.Column("errors_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["sentence_id"], ["sentence.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["translation_run_id"], ["translation_run.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_sentence_ir_sentence_id"), "sentence_ir", ["sentence_id"], unique=False)
    op.create_index(op.f("ix_sentence_ir_translation_run_id"), "sentence_ir", ["translation_run_id"], unique=False)
    op.create_index(
        "ix_sentence_ir_run_sentence",
        "sentence_ir",
        ["translation_run_id", "sentence_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_sentence_ir_run_sentence", table_name="sentence_ir")
    op.drop_index(op.f("ix_sentence_ir_translation_run_id"), table_name="sentence_ir")
    op.drop_index(op.f("ix_sentence_ir_sentence_id"), table_name="sentence_ir")
    op.drop_table("sentence_ir")
