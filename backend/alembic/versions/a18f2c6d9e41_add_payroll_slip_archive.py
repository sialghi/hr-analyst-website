"""Add durable payroll slip archive

Revision ID: a18f2c6d9e41
Revises: d4e8b7c0a913
Create Date: 2026-10-13

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a18f2c6d9e41"
down_revision: Union[str, Sequence[str], None] = "d4e8b7c0a913"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "payroll_slip_archives",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("employee_id", sa.Integer(), nullable=False),
        sa.Column("payroll_period", sa.String(), nullable=False),
        sa.Column("employee_name", sa.String(), nullable=False),
        sa.Column("pdf_bytes", sa.LargeBinary(), nullable=False),
        sa.Column("saved_by_user_id", sa.Integer(), nullable=True),
        sa.Column("saved_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["employee_id"], ["employees.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["saved_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("employee_id", "payroll_period", name="uq_payroll_slip_employee_period"),
    )
    op.create_index(
        op.f("ix_payroll_slip_archives_id"),
        "payroll_slip_archives",
        ["id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_payroll_slip_archives_employee_id"),
        "payroll_slip_archives",
        ["employee_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_payroll_slip_archives_payroll_period"),
        "payroll_slip_archives",
        ["payroll_period"],
        unique=False,
    )
    op.create_index(
        op.f("ix_payroll_slip_archives_saved_at"),
        "payroll_slip_archives",
        ["saved_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_payroll_slip_archives_expires_at"),
        "payroll_slip_archives",
        ["expires_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_payroll_slip_archives_expires_at"),
        table_name="payroll_slip_archives",
    )
    op.drop_index(
        op.f("ix_payroll_slip_archives_saved_at"),
        table_name="payroll_slip_archives",
    )
    op.drop_index(
        op.f("ix_payroll_slip_archives_payroll_period"),
        table_name="payroll_slip_archives",
    )
    op.drop_index(
        op.f("ix_payroll_slip_archives_employee_id"),
        table_name="payroll_slip_archives",
    )
    op.drop_index(
        op.f("ix_payroll_slip_archives_id"),
        table_name="payroll_slip_archives",
    )
    op.drop_table("payroll_slip_archives")
