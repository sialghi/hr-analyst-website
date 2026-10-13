"""Add payroll WhatsApp delivery history

Revision ID: d4e8b7c0a913
Revises: 8b7a2f1c9d34
Create Date: 2026-10-13

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d4e8b7c0a913"
down_revision: Union[str, Sequence[str], None] = "8b7a2f1c9d34"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "payroll_whatsapp_deliveries",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("payroll_session_id", sa.String(length=32), nullable=False),
        sa.Column("row_index", sa.Integer(), nullable=False),
        sa.Column("employee_id", sa.Integer(), nullable=True),
        sa.Column("employee_code", sa.String(), nullable=True),
        sa.Column("employee_name", sa.String(), nullable=False),
        sa.Column("payroll_period", sa.String(), nullable=False),
        sa.Column("recipient_phone", sa.String(), nullable=True),
        sa.Column("requested_by_user_id", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("text_status", sa.String(), nullable=True),
        sa.Column("pdf_status", sa.String(), nullable=True),
        sa.Column("error_detail", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ["employee_id"],
            ["employees.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["requested_by_user_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_payroll_whatsapp_deliveries_id"),
        "payroll_whatsapp_deliveries",
        ["id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_payroll_whatsapp_deliveries_payroll_session_id"),
        "payroll_whatsapp_deliveries",
        ["payroll_session_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_payroll_whatsapp_deliveries_employee_id"),
        "payroll_whatsapp_deliveries",
        ["employee_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_payroll_whatsapp_deliveries_payroll_period"),
        "payroll_whatsapp_deliveries",
        ["payroll_period"],
        unique=False,
    )
    op.create_index(
        op.f("ix_payroll_whatsapp_deliveries_requested_by_user_id"),
        "payroll_whatsapp_deliveries",
        ["requested_by_user_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_payroll_whatsapp_deliveries_status"),
        "payroll_whatsapp_deliveries",
        ["status"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_payroll_whatsapp_deliveries_status"),
        table_name="payroll_whatsapp_deliveries",
    )
    op.drop_index(
        op.f("ix_payroll_whatsapp_deliveries_requested_by_user_id"),
        table_name="payroll_whatsapp_deliveries",
    )
    op.drop_index(
        op.f("ix_payroll_whatsapp_deliveries_payroll_period"),
        table_name="payroll_whatsapp_deliveries",
    )
    op.drop_index(
        op.f("ix_payroll_whatsapp_deliveries_employee_id"),
        table_name="payroll_whatsapp_deliveries",
    )
    op.drop_index(
        op.f("ix_payroll_whatsapp_deliveries_payroll_session_id"),
        table_name="payroll_whatsapp_deliveries",
    )
    op.drop_index(
        op.f("ix_payroll_whatsapp_deliveries_id"),
        table_name="payroll_whatsapp_deliveries",
    )
    op.drop_table("payroll_whatsapp_deliveries")
