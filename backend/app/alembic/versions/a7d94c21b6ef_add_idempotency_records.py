"""add idempotency records

Revision ID: a7d94c21b6ef
Revises: 9e7e97f31478
Create Date: 2026-09-10

"""

from alembic import op
import sqlalchemy as sa
import sqlmodel.sql.sqltypes


revision = "a7d94c21b6ef"
down_revision = "9e7e97f31478"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "idempotency_record",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column(
            "idempotency_key",
            sqlmodel.sql.sqltypes.AutoString(length=255),
            nullable=False,
        ),
        sa.Column(
            "request_hash",
            sqlmodel.sql.sqltypes.AutoString(length=64),
            nullable=False,
        ),
        sa.Column("resource_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organization.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "organization_id",
            "user_id",
            "idempotency_key",
            name="uq_idempotency_record_scope",
        ),
    )
    op.create_index(
        op.f("ix_idempotency_record_organization_id"),
        "idempotency_record",
        ["organization_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_idempotency_record_resource_id"),
        "idempotency_record",
        ["resource_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_idempotency_record_user_id"),
        "idempotency_record",
        ["user_id"],
        unique=False,
    )


def downgrade():
    op.drop_index(
        op.f("ix_idempotency_record_user_id"),
        table_name="idempotency_record",
    )
    op.drop_index(
        op.f("ix_idempotency_record_resource_id"),
        table_name="idempotency_record",
    )
    op.drop_index(
        op.f("ix_idempotency_record_organization_id"),
        table_name="idempotency_record",
    )
    op.drop_table("idempotency_record")
