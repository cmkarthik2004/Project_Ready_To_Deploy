"""document structure, fact origin / fiscal year / total flag on metrics, saved dashboards

Revision ID: b7d4e2a91c05
Revises: a3c91d2e7f10
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "b7d4e2a91c05"
down_revision: Union[str, Sequence[str], None] = "a3c91d2e7f10"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("documents", sa.Column("structure", postgresql.JSONB(), nullable=True))
    op.add_column("financial_metrics", sa.Column("value_origin", sa.String(20), nullable=False, server_default="reported"))
    op.add_column("financial_metrics", sa.Column("fiscal_year", sa.Integer(), nullable=True))
    op.add_column("financial_metrics", sa.Column("is_total", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.create_index("ix_financial_metrics_fiscal_year", "financial_metrics", ["fiscal_year"])
    op.create_table(
        "dashboards",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("owner_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("filters", postgresql.JSONB(), nullable=False),
        sa.Column("layout", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("owner_id", "name"),
    )
    op.create_index("ix_dashboards_owner_id", "dashboards", ["owner_id"])


def downgrade() -> None:
    op.drop_index("ix_dashboards_owner_id", table_name="dashboards")
    op.drop_table("dashboards")
    op.drop_index("ix_financial_metrics_fiscal_year", table_name="financial_metrics")
    op.drop_column("financial_metrics", "is_total")
    op.drop_column("financial_metrics", "fiscal_year")
    op.drop_column("financial_metrics", "value_origin")
    op.drop_column("documents", "structure")
