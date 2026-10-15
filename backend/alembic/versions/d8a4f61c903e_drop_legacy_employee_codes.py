"""Validate canonical employee-code columns after production cutover.

Revision ID: d8a4f61c903e
Revises: c91e4b7d2a60
Create Date: 2026-10-15
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d8a4f61c903e"
down_revision: Union[str, Sequence[str], None] = "c91e4b7d2a60"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    connection = op.get_bind()
    for table_name in ("employees", "employee_import_candidates"):
        missing_count = connection.execute(
            sa.text(f"SELECT COUNT(*) FROM {table_name} WHERE employee_code IS NULL")
        ).scalar_one()
        if missing_count and table_name == "employee_import_candidates":
            raise RuntimeError(
                f"Employee ID cutover incomplete: {table_name} has {missing_count} rows without employee_code."
            )


def downgrade() -> None:
    raise RuntimeError("Employee-code cutover cannot be safely downgraded.")
