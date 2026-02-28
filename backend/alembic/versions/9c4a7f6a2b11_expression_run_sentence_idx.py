"""add expression run sentence relation index

Revision ID: 9c4a7f6a2b11
Revises: 8d9b7b7a3a63
Create Date: 2026-02-28 17:40:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "9c4a7f6a2b11"
down_revision: Union[str, Sequence[str], None] = "8d9b7b7a3a63"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("expression", sa.Column("translation_run_id", sa.BigInteger(), nullable=True))
    op.add_column("expression", sa.Column("sentence_id", sa.BigInteger(), nullable=True))
    op.add_column("expression", sa.Column("relation_index", sa.Integer(), nullable=False, server_default="0"))

    op.create_foreign_key(
        "fk_expression_translation_run_id",
        "expression",
        "translation_run",
        ["translation_run_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_expression_sentence_id",
        "expression",
        "sentence",
        ["sentence_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index(op.f("ix_expression_translation_run_id"), "expression", ["translation_run_id"], unique=False)
    op.create_index(op.f("ix_expression_sentence_id"), "expression", ["sentence_id"], unique=False)
    op.create_index(
        "ix_expression_run_sentence_relation_idx",
        "expression",
        ["translation_run_id", "sentence_id", "relation_index"],
        unique=True,
    )

    op.alter_column("expression", "relation_index", server_default=None)


def downgrade() -> None:
    op.drop_index("ix_expression_run_sentence_relation_idx", table_name="expression")
    op.drop_index(op.f("ix_expression_sentence_id"), table_name="expression")
    op.drop_index(op.f("ix_expression_translation_run_id"), table_name="expression")
    op.drop_constraint("fk_expression_sentence_id", "expression", type_="foreignkey")
    op.drop_constraint("fk_expression_translation_run_id", "expression", type_="foreignkey")
    op.drop_column("expression", "relation_index")
    op.drop_column("expression", "sentence_id")
    op.drop_column("expression", "translation_run_id")
