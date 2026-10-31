"""add scoped producer credentials

Revision ID: c9df16169911
Revises: 163f0de455ee
Create Date: 2026-10-31 12:29:31.767571

"""
from typing import Sequence, Union

from alembic import op, context
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c9df16169911'
down_revision: Union[str, Sequence[str], None] = '163f0de455ee'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('producer_credentials',
    sa.Column('integration_id', sa.Uuid(), nullable=False),
    sa.Column('token_hash', sa.String(length=64), nullable=False),
    sa.Column('revoked', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("token_hash ~ '^[0-9a-f]{64}$'", name=op.f('ck_producer_credentials_sha256_hex')),
    sa.ForeignKeyConstraint(['integration_id'], ['integrations.id'], name=op.f('fk_producer_credentials_integration_id_integrations'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_producer_credentials')),
    sa.UniqueConstraint('token_hash', name=op.f('uq_producer_credentials_token_hash'))
    )
    op.create_index('ix_producer_credentials_integration', 'producer_credentials', ['integration_id'], unique=False)


def downgrade() -> None:
    """Credential deletion requires an explicit disposable-data override."""
    allowed = context.get_x_argument(as_dictionary=True).get("allow_data_loss") == "true"
    if not allowed and not context.config.attributes.get("allow_data_loss", False):
        raise RuntimeError("Downgrade deletes history and credentials; use -x allow_data_loss=true only for disposable data")
    op.drop_index('ix_producer_credentials_integration', table_name='producer_credentials')
    op.drop_table('producer_credentials')
