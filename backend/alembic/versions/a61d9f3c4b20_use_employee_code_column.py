"""Use employee_code as the physical employee identifier column.

Revision ID: a61d9f3c4b20
Revises: f3a9b6c1d843
Create Date: 2026-10-15
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a61d9f3c4b20"
down_revision: Union[str, Sequence[str], None] = "f3a9b6c1d843"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


TABLES = (
    "employees",
    "employee_import_candidates",
    "payroll_whatsapp_deliveries",
    "attendance_recap_records",
)
UNIQUE_TABLES = {"employees", "employee_import_candidates"}


def _columns(connection, table_name: str) -> set[str]:
    return {
        column["name"]
        for column in sa.inspect(connection).get_columns(table_name)
    }


def _drop_employee_id_indexes(connection, table_name: str) -> None:
    for index in sa.inspect(connection).get_indexes(table_name):
        if set(index.get("column_names") or ()) & {"employee_code", "new_employee_id"}:
            op.drop_index(index["name"], table_name=table_name)


def upgrade() -> None:
    connection = op.get_bind()

    for table_name in TABLES:
        columns = _columns(connection, table_name)
        if "new_employee_id" not in columns and "employee_code" not in columns:
            raise RuntimeError(f"{table_name} has no employee ID column to migrate.")
        _drop_employee_id_indexes(connection, table_name)
        columns = _columns(connection, table_name)

        if "new_employee_id" in columns and "employee_code" in columns:
            connection.execute(
                sa.text(
                    f"UPDATE {table_name} SET employee_code = new_employee_id"
                )
            )
            with op.batch_alter_table(table_name) as batch_op:
                batch_op.drop_column("new_employee_id")
        elif "new_employee_id" in columns:
            with op.batch_alter_table(table_name) as batch_op:
                batch_op.alter_column(
                    "new_employee_id",
                    new_column_name="employee_code",
                    existing_type=sa.String(),
                )

        op.create_index(
            f"ix_{table_name}_employee_code",
            table_name,
            ["employee_code"],
            unique=table_name in UNIQUE_TABLES,
        )


def downgrade() -> None:
    raise RuntimeError(
        "The employee_code physical column is the production schema; "
        "restore a verified backup to reverse this migration."
    )
