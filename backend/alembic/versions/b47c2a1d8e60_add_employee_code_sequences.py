"""Add branch-scoped employee code sequences

Revision ID: b47c2a1d8e60
Revises: a18f2c6d9e41
Create Date: 2026-10-15

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b47c2a1d8e60"
down_revision: Union[str, Sequence[str], None] = "a18f2c6d9e41"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


BRANCH_CODES = ("01", "02", "03", "04", "05", "06", "07", "08", "09")


def upgrade() -> None:
    op.create_table(
        "employee_code_sequences",
        sa.Column("branch_code", sa.String(length=2), nullable=False),
        sa.Column("next_serial", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("branch_code"),
    )
    op.bulk_insert(
        sa.table(
            "employee_code_sequences",
            sa.column("branch_code", sa.String(length=2)),
            sa.column("next_serial", sa.Integer()),
        ),
        [{"branch_code": branch_code, "next_serial": 1} for branch_code in BRANCH_CODES],
    )


def downgrade() -> None:
    op.drop_table("employee_code_sequences")
