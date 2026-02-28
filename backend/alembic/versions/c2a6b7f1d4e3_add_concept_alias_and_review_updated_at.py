"""add concept_alias and review_queue updated_at

Revision ID: c2a6b7f1d4e3
Revises: 478d80d7421a
Create Date: 2026-02-28 20:50:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "c2a6b7f1d4e3"
down_revision: Union[str, Sequence[str], None] = "478d80d7421a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "concept_alias",
        sa.Column("id", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), autoincrement=True, nullable=False),
        sa.Column("old_uid", sa.String(length=255), nullable=False),
        sa.Column("new_uid", sa.String(length=255), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("old_uid"),
    )
    op.create_index(op.f("ix_concept_alias_new_uid"), "concept_alias", ["new_uid"], unique=False)

    op.add_column(
        "review_queue",
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )


def downgrade() -> None:
    op.drop_column("review_queue", "updated_at")
    op.drop_index(op.f("ix_concept_alias_new_uid"), table_name="concept_alias")
    op.drop_table("concept_alias")
