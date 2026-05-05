"""add message source document name

Revision ID: 20260504_0003
Revises: 20260503_0002
Create Date: 2026-05-04 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260504_0003"
down_revision: str | None = "20260503_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "message_sources",
        sa.Column("document_name", sa.Text(), nullable=True),
    )
    op.execute(
        """
        UPDATE message_sources
        SET document_name = documents.display_name
        FROM documents
        WHERE message_sources.document_id = documents.id
        """
    )
    op.execute(
        """
        UPDATE message_sources
        SET document_name = 'Unknown document'
        WHERE document_name IS NULL
        """
    )
    op.alter_column(
        "message_sources",
        "document_name",
        existing_type=sa.Text(),
        nullable=False,
    )


def downgrade() -> None:
    op.drop_column("message_sources", "document_name")
