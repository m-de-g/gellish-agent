"""add partial unique index for open review_queue items

Revision ID: f4a8d34c1b72
Revises: c2a6b7f1d4e3
Create Date: 2026-03-01 12:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "f4a8d34c1b72"
down_revision: Union[str, Sequence[str], None] = "c2a6b7f1d4e3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        "uq_review_queue_open_item",
        "review_queue",
        ["item_type", "item_ref"],
        unique=True,
        postgresql_where=sa.text("status = 'open'"),
    )


def downgrade() -> None:
    op.drop_index("uq_review_queue_open_item", table_name="review_queue")
