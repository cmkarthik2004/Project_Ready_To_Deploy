"""fulltext index on chunks

Revision ID: 6b5745dcb0d5
Revises: 240743bee225
Create Date: 2026-11-23 18:29:42.714972

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '6b5745dcb0d5'
down_revision: Union[str, Sequence[str], None] = '240743bee225'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """GIN index used by the lexical half of hybrid retrieval."""
    op.execute("CREATE INDEX IF NOT EXISTS ix_chunks_fts ON document_chunks USING gin (to_tsvector('english', text))")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_chunks_fts")
