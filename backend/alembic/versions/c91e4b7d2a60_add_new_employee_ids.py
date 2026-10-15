"""Align the canonical employee identifier column and sequence names.

Revision ID: c91e4b7d2a60
Revises: b47c2a1d8e60
Create Date: 2026-10-15
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c91e4b7d2a60"
down_revision: Union[str, Sequence[str], None] = "b47c2a1d8e60"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    connection = op.get_bind()
    op.rename_table("employee_code_sequences", "employee_id_sequences")

    expected_tables = (
        "employees",
        "employee_import_candidates",
        "payroll_whatsapp_deliveries",
        "attendance_recap_records",
    )
    for table_name in expected_tables:
        columns = {column["name"] for column in sa.inspect(connection).get_columns(table_name)}
        if "employee_code" not in columns:
            raise RuntimeError(
                f"{table_name} must contain employee_code before the employee-ID cutover."
            )
        indexes = {index["name"] for index in sa.inspect(connection).get_indexes(table_name)}
        index_name = f"ix_{table_name}_employee_code"
        if index_name not in indexes:
            op.create_index(
                index_name,
                table_name,
                ["employee_code"],
                unique=table_name in ("employees", "employee_import_candidates"),
            )


def downgrade() -> None:
    op.rename_table("employee_id_sequences", "employee_code_sequences")
