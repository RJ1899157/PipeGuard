"""initial execution metadata

Revision ID: 825e5c183adc
Revises:
Create Date: 2026-10-31 12:17:29.686549

"""
from typing import Sequence, Union

from alembic import op, context
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '825e5c183adc'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('datasets',
    sa.Column('namespace', sa.String(length=512), nullable=False),
    sa.Column('name', sa.String(length=512), nullable=False),
    sa.Column('kind', sa.String(length=100), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_datasets')),
    sa.UniqueConstraint('namespace', 'name', name=op.f('uq_datasets_namespace'))
    )
    op.create_table('integrations',
    sa.Column('name', sa.String(length=255), nullable=False),
    sa.Column('environment', sa.String(length=100), nullable=False),
    sa.Column('kind', sa.String(length=100), nullable=False),
    sa.Column('secret_ref', sa.Text(), nullable=True),
    sa.Column('enabled', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_integrations')),
    sa.UniqueConstraint('environment', 'name', name=op.f('uq_integrations_environment'))
    )
    op.create_table('ingested_events',
    sa.Column('integration_id', sa.Uuid(), nullable=False),
    sa.Column('deduplication_key', sa.String(length=512), nullable=False),
    sa.Column('event_type', sa.String(length=100), nullable=False),
    sa.Column('schema_version', sa.Integer(), nullable=False),
    sa.Column('occurred_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('received_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('payload_hash', sa.String(length=64), nullable=False),
    sa.Column('canonicalization_version', sa.String(length=100), nullable=False),
    sa.Column('redaction_version', sa.String(length=100), nullable=False),
    sa.Column('processing_state', sa.String(length=20), server_default='pending', nullable=False),
    sa.Column('processing_error', sa.Text(), nullable=True),
    sa.Column('processed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("jsonb_typeof(payload) = 'object'", name=op.f('ck_ingested_events_payload_object')),
    sa.CheckConstraint("payload_hash ~ '^[0-9a-f]{64}$'", name=op.f('ck_ingested_events_sha256_hex')),
    sa.CheckConstraint("processing_state IN ('pending', 'processed', 'failed')", name=op.f('ck_ingested_events_processing_state')),
    sa.CheckConstraint('schema_version >= 1', name=op.f('ck_ingested_events_positive_schema_version')),
    sa.ForeignKeyConstraint(['integration_id'], ['integrations.id'], name=op.f('fk_ingested_events_integration_id_integrations'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_ingested_events')),
    sa.UniqueConstraint('integration_id', 'deduplication_key', name=op.f('uq_ingested_events_integration_id'))
    )
    op.create_index('ix_events_processing_received', 'ingested_events', ['processing_state', 'received_at'], unique=False)
    op.create_table('jobs',
    sa.Column('integration_id', sa.Uuid(), nullable=False),
    sa.Column('namespace', sa.String(length=512), nullable=False),
    sa.Column('name', sa.String(length=512), nullable=False),
    sa.Column('kind', sa.String(length=100), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['integration_id'], ['integrations.id'], name=op.f('fk_jobs_integration_id_integrations'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_jobs')),
    sa.UniqueConstraint('integration_id', 'namespace', 'name', name=op.f('uq_jobs_integration_id'))
    )
    op.create_table('runs',
    sa.Column('job_id', sa.Uuid(), nullable=False),
    sa.Column('external_run_id', sa.String(length=512), nullable=False),
    sa.Column('parent_run_id', sa.Uuid(), nullable=True),
    sa.Column('state', sa.String(length=20), server_default='unknown', nullable=False),
    sa.Column('data_interval_start', sa.DateTime(timezone=True), nullable=True),
    sa.Column('data_interval_end', sa.DateTime(timezone=True), nullable=True),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("state IN ('unknown', 'queued', 'running', 'succeeded', 'failed', 'cancelled')", name=op.f('ck_runs_state')),
    sa.CheckConstraint('data_interval_end >= data_interval_start', name=op.f('ck_runs_interval_order')),
    sa.CheckConstraint('parent_run_id IS NULL OR parent_run_id <> id', name=op.f('ck_runs_not_own_parent')),
    sa.ForeignKeyConstraint(['job_id'], ['jobs.id'], name=op.f('fk_runs_job_id_jobs'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['parent_run_id'], ['runs.id'], name=op.f('fk_runs_parent_run_id_runs'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_runs')),
    sa.UniqueConstraint('job_id', 'external_run_id', name=op.f('uq_runs_job_id'))
    )
    op.create_index('ix_runs_job_started', 'runs', ['job_id', 'started_at'], unique=False)
    op.create_index('ix_runs_parent', 'runs', ['parent_run_id'], unique=False)
    op.create_table('attempts',
    sa.Column('run_id', sa.Uuid(), nullable=False),
    sa.Column('attempt_key', sa.String(length=512), nullable=False),
    sa.Column('attempt_number', sa.Integer(), nullable=False),
    sa.Column('state', sa.String(length=20), server_default='unknown', nullable=False),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('error_code', sa.String(length=255), nullable=True),
    sa.Column('error_message', sa.Text(), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("state IN ('unknown', 'queued', 'running', 'succeeded', 'failed', 'cancelled')", name=op.f('ck_attempts_state')),
    sa.CheckConstraint('attempt_number >= 1', name=op.f('ck_attempts_positive_number')),
    sa.ForeignKeyConstraint(['run_id'], ['runs.id'], name=op.f('fk_attempts_run_id_runs'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_attempts')),
    sa.UniqueConstraint('run_id', 'attempt_key', 'attempt_number', name=op.f('uq_attempts_run_id'))
    )
    op.execute("""
        CREATE FUNCTION protect_ingested_event() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP = 'DELETE' OR TG_OP = 'TRUNCATE' THEN
                RAISE EXCEPTION 'Source event history cannot be deleted';
            END IF;
            IF (to_jsonb(NEW) - ARRAY['processing_state', 'processing_error', 'processed_at'])
                IS DISTINCT FROM
               (to_jsonb(OLD) - ARRAY['processing_state', 'processing_error', 'processed_at']) THEN
                RAISE EXCEPTION 'Source event content is immutable';
            END IF;
            RETURN NEW;
        END;
        $$
    """)
    op.execute("""
        CREATE TRIGGER protect_event_rows BEFORE UPDATE OR DELETE ON ingested_events
        FOR EACH ROW EXECUTE FUNCTION protect_ingested_event()
    """)
    op.execute("""
        CREATE TRIGGER protect_event_truncate BEFORE TRUNCATE ON ingested_events
        FOR EACH STATEMENT EXECUTE FUNCTION protect_ingested_event()
    """)


def downgrade() -> None:
    """Destructive reset, permitted only by an explicit operator override."""
    allowed = context.get_x_argument(as_dictionary=True).get("allow_data_loss") == "true"
    if not allowed and not context.config.attributes.get("allow_data_loss", False):
        raise RuntimeError("Initial downgrade deletes history; use -x allow_data_loss=true only for disposable data")
    op.drop_table('attempts')
    op.drop_index('ix_runs_parent', table_name='runs')
    op.drop_index('ix_runs_job_started', table_name='runs')
    op.drop_table('runs')
    op.drop_table('jobs')
    op.drop_index('ix_events_processing_received', table_name='ingested_events')
    op.drop_table('ingested_events')
    op.execute('DROP FUNCTION protect_ingested_event()')
    op.drop_table('integrations')
    op.drop_table('datasets')
