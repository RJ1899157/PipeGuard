"""record execution reconciliation flags

Revision ID: 163f0de455ee
Revises: 825e5c183adc
Create Date: 2026-10-31 12:23:00.617662

"""
from typing import Sequence, Union

from alembic import op, context
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '163f0de455ee'
down_revision: Union[str, Sequence[str], None] = '825e5c183adc'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('attempts', sa.Column('reconciliation_required', sa.Boolean(), server_default=sa.text('false'), nullable=False))
    op.add_column('runs', sa.Column('reconciliation_required', sa.Boolean(), server_default=sa.text('false'), nullable=False))


def downgrade() -> None:
    """Removing uncertainty flags is destructive and requires an explicit override."""
    allowed = context.get_x_argument(as_dictionary=True).get("allow_data_loss") == "true"
    if not allowed and not context.config.attributes.get("allow_data_loss", False):
        raise RuntimeError("Downgrade deletes history flags; use -x allow_data_loss=true only for disposable data")
    op.drop_column('runs', 'reconciliation_required')
    op.drop_column('attempts', 'reconciliation_required')
