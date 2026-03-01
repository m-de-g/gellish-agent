"""add export_artifact table

Revision ID: d9b2c7a1e4f0
Revises: a1f9d2b4c6e7
Create Date: 2026-03-01 21:05:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "d9b2c7a1e4f0"
down_revision: Union[str, Sequence[str], None] = "a1f9d2b4c6e7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "export_artifact",
        sa.Column("id", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), autoincrement=True, nullable=False),
        sa.Column("translation_run_id", sa.BigInteger(), nullable=False),
        sa.Column("format", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("storage_path", sa.Text(), nullable=False),
        sa.Column("sha256", sa.Text(), nullable=True),
        sa.Column("row_count", sa.Integer(), nullable=True),
        sa.Column("schema_version", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("meta_json", sa.JSON(), nullable=True),
        sa.ForeignKeyConstraint(["translation_run_id"], ["translation_run.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("storage_path"),
    )
    op.create_index(op.f("ix_export_artifact_translation_run_id"), "export_artifact", ["translation_run_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_export_artifact_translation_run_id"), table_name="export_artifact")
    op.drop_table("export_artifact")
