"""Add employee PHL-to-PKWT transition history

Revision ID: 8b7a2f1c9d34
Revises: 520dd626c0c9
Create Date: 2026-10-12

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "8b7a2f1c9d34"
down_revision: Union[str, Sequence[str], None] = "520dd626c0c9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "employee_employment_transitions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("employee_id", sa.Integer(), nullable=False),
        sa.Column("employment_contract_id", sa.Integer(), nullable=False),
        sa.Column("phl_start_date", sa.Date(), nullable=False),
        sa.Column("phl_end_date", sa.Date(), nullable=False),
        sa.Column("transition_date", sa.Date(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ["employee_id"],
            ["employees.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["employment_contract_id"],
            ["employment_contracts.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("employment_contract_id"),
    )
    op.create_index(
        op.f("ix_employee_employment_transitions_id"),
        "employee_employment_transitions",
        ["id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_employee_employment_transitions_employee_id"),
        "employee_employment_transitions",
        ["employee_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_employee_employment_transitions_employee_id"),
        table_name="employee_employment_transitions",
    )
    op.drop_index(
        op.f("ix_employee_employment_transitions_id"),
        table_name="employee_employment_transitions",
    )
    op.drop_table("employee_employment_transitions")
