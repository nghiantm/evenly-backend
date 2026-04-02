"""add category to expenses

Revision ID: 0003
Revises: 0002
Create Date: 2026-04-01 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "expenses",
        sa.Column("category", sa.String(100), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("expenses", "category")
