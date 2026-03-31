"""add exchange_rate to expenses

Revision ID: 0002
Revises: 0001
Create Date: 2026-03-31 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "expenses",
        sa.Column(
            "exchange_rate",
            sa.Numeric(14, 6),
            nullable=False,
            server_default="1",
        ),
    )


def downgrade() -> None:
    op.drop_column("expenses", "exchange_rate")
