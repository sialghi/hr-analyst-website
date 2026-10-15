"""Make employee deletion recoverable.

Revision ID: f3a9b6c1d843
Revises: e5c1a8d7f302
Create Date: 2026-10-15
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f3a9b6c1d843"
down_revision: Union[str, Sequence[str], None] = "e5c1a8d7f302"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("employees", sa.Column("deleted_at", sa.DateTime(), nullable=True))
    op.add_column(
        "employees",
        sa.Column("deleted_previous_active", sa.Boolean(), nullable=True),
    )
    op.create_index("ix_employees_deleted_at", "employees", ["deleted_at"])


def downgrade() -> None:
    op.drop_index("ix_employees_deleted_at", table_name="employees")
    op.drop_column("employees", "deleted_previous_active")
    op.drop_column("employees", "deleted_at")
