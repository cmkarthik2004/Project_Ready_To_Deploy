"""unique (owner_id, sha256) on documents: duplicate uploads are rejected even when two arrive concurrently

Revision ID: a3c91d2e7f10
Revises: 6b5745dcb0d5
"""
from typing import Sequence, Union

from alembic import op

revision: str = "a3c91d2e7f10"
down_revision: Union[str, Sequence[str], None] = "6b5745dcb0d5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_index("ix_documents_owner_sha", table_name="documents")
    op.create_index("ix_documents_owner_sha", "documents", ["owner_id", "sha256"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_documents_owner_sha", table_name="documents")
    op.create_index("ix_documents_owner_sha", "documents", ["owner_id", "sha256"])
