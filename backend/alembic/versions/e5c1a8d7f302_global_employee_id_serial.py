"""Use one global employee ID serial across all branches.

Revision ID: e5c1a8d7f302
Revises: d8a4f61c903e
Create Date: 2026-10-15
"""
import re
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e5c1a8d7f302"
down_revision: Union[str, Sequence[str], None] = "d8a4f61c903e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


BRANCH_PREFIXES = {"01", "02", "03", "04", "05", "06", "07", "08", "09"}
EMPLOYEE_ID_PATTERN = re.compile(r"JIP-(\d{2})(\d{4})", re.IGNORECASE)


def _serial(value: str | None) -> int | None:
    if not value:
        return None
    match = EMPLOYEE_ID_PATTERN.fullmatch(value.strip())
    if not match or match.group(1) not in BRANCH_PREFIXES:
        return None
    return int(match.group(2))


def upgrade() -> None:
    connection = op.get_bind()
    serials = []
    serial_owners = {}
    for table_name in ("employees", "employee_import_candidates"):
        if table_name == "employees":
            rows = connection.execute(
                sa.text("SELECT id, employee_code FROM employees")
            )
        else:
            rows = connection.execute(
                sa.text(
                    "SELECT approved_employee_id, employee_code "
                    "FROM employee_import_candidates"
                )
            )
        for owner_id, value in rows:
            serial = _serial(value)
            if serial is None:
                continue
            serials.append(serial)
            previous = serial_owners.get(serial)
            if previous is not None:
                previous_table, previous_id, previous_value = previous
                linked_approved_candidate = (
                    table_name == "employee_import_candidates"
                    and previous_table == "employees"
                    and owner_id == previous_id
                    and value.strip().casefold() == previous_value.strip().casefold()
                )
                if not linked_approved_candidate:
                    raise RuntimeError(
                        f"Employee ID serial {serial:04d} is duplicated in "
                        f"{previous_table} and {table_name}; resolve conflicts before migration."
                    )
            else:
                serial_owners[serial] = (table_name, owner_id, value)

    previous_sequence_values = [
        row[0]
        for row in connection.execute(
            sa.text("SELECT next_serial FROM employee_id_sequences")
        )
    ]
    max_used = max(
        [
            *serials,
            *(value - 1 for value in previous_sequence_values),
            0,
        ]
    )

    op.create_table(
        "employee_id_sequences_global",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("next_serial", sa.Integer(), nullable=False),
        sa.CheckConstraint("id = 1", name="ck_employee_id_sequences_singleton"),
        sa.PrimaryKeyConstraint("id"),
    )
    connection.execute(
        sa.text(
            "INSERT INTO employee_id_sequences_global (id, next_serial) "
            "VALUES (1, :next_serial)"
        ),
        {"next_serial": max_used + 1},
    )
    op.drop_table("employee_id_sequences")
    op.rename_table("employee_id_sequences_global", "employee_id_sequences")


def downgrade() -> None:
    raise RuntimeError(
        "A global employee serial cannot safely downgrade to per-branch allocation. "
        "Restore a verified pre-migration backup instead."
    )
