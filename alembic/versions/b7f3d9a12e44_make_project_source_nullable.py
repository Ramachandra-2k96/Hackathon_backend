"""Make project source fields nullable

Revision ID: b7f3d9a12e44
Revises: f4a9c2d1e7b3
Create Date: 2026-04-23 00:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b7f3d9a12e44'
down_revision: Union[str, Sequence[str], None] = 'f4a9c2d1e7b3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('projects') as batch_op:
        batch_op.alter_column('source_type', existing_type=sa.String(), nullable=True)
        batch_op.alter_column('zip_file_url', existing_type=sa.String(), nullable=True)


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('projects') as batch_op:
        batch_op.alter_column('zip_file_url', existing_type=sa.String(), nullable=False)
        batch_op.alter_column('source_type', existing_type=sa.String(), nullable=False)
