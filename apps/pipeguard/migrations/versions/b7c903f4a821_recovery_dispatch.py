"""Separate executable approvals and append-only dispatch/reconciliation history.

Revision ID: b7c903f4a821
Revises: f102b8e6d391
"""
from alembic import context, op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "b7c903f4a821"
down_revision = "f102b8e6d391"
branch_labels = None
depends_on = None
TABLES = ("recovery_actions", "recovery_action_decisions", "recovery_dispatches", "recovery_dispatch_events")


def record_columns():
    return [sa.Column("id", sa.Uuid(), primary_key=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now())]


def reference(name, target, **options):
    return sa.Column(name, sa.Uuid(), sa.ForeignKey(target + ".id", ondelete="RESTRICT"), nullable=False, **options)


def bounded_payload():
    return [sa.Column("payload", JSONB(), nullable=False), sa.Column("payload_hash", sa.String(64), nullable=False),
        sa.CheckConstraint("payload_hash ~ '^[0-9a-f]{64}$'", name="sha256_hex"),
        sa.CheckConstraint("jsonb_typeof(payload) = 'object' AND octet_length(payload::text) <= 16384", name="bounded_payload")]


def upgrade():
    op.create_table("recovery_actions", reference("incident_id", "incidents"), reference("bundle_id", "evidence_bundles"),
        sa.Column("request_key", sa.Uuid(), nullable=False, unique=True), sa.Column("actor", sa.String(40), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False), *bounded_payload(), *record_columns(),
        sa.CheckConstraint("expires_at > created_at AND expires_at <= created_at + interval '10 minutes'", name="expiry"))
    op.create_index("ix_recovery_actions_incident", "recovery_actions", ["incident_id", "created_at", "id"])
    op.create_table("recovery_action_decisions", reference("action_id", "recovery_actions"),
        sa.Column("request_key", sa.Uuid(), nullable=False, unique=True), sa.Column("proposal_hash", sa.String(64), nullable=False),
        sa.Column("decision", sa.String(10), nullable=False), sa.Column("actor", sa.String(40), nullable=False), *record_columns(),
        sa.UniqueConstraint("action_id", "decision"), sa.CheckConstraint("proposal_hash ~ '^[0-9a-f]{64}$'", name="sha256_hex"),
        sa.CheckConstraint("decision IN ('approve', 'reject', 'cancel')", name="decision"))
    op.create_index("ix_recovery_action_decision_terminal", "recovery_action_decisions", ["action_id"], unique=True,
                    postgresql_where=sa.text("decision <> 'cancel'"))
    op.create_table("recovery_dispatches", reference("action_id", "recovery_actions", unique=True),
        reference("approval_id", "recovery_action_decisions", unique=True), reference("failed_run_id", "runs", unique=True),
        reference("job_id", "jobs"), sa.Column("external_run_id", sa.String(100), nullable=False, unique=True),
        sa.Column("request_key", sa.Uuid(), nullable=False, unique=True), sa.Column("actor", sa.String(40), nullable=False),
        *bounded_payload(), *record_columns())
    op.create_index("ix_recovery_dispatches_job", "recovery_dispatches", ["job_id", "created_at", "id"])
    op.create_table("recovery_dispatch_events", reference("dispatch_id", "recovery_dispatches"),
        sa.Column("request_key", sa.Uuid(), nullable=False, unique=True), sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(20), nullable=False), sa.Column("state", sa.String(20), nullable=False),
        sa.Column("code", sa.String(80), nullable=False), sa.Column("facts", JSONB(), nullable=False), *record_columns(),
        sa.UniqueConstraint("dispatch_id", "sequence"), sa.CheckConstraint("sequence BETWEEN 1 AND 100", name="sequence_bound"),
        sa.CheckConstraint("source IN ('dispatch', 'reconcile')", name="source"),
        sa.CheckConstraint("state IN ('unknown', 'accepted', 'rejected', 'queued', 'running', 'succeeded', 'failed', 'conflict')", name="state"),
        sa.CheckConstraint("code ~ '^[a-z_]{1,80}$'", name="safe_code"),
        sa.CheckConstraint("jsonb_typeof(facts) = 'object' AND octet_length(facts::text) <= 2048", name="bounded_facts"))
    for table in TABLES:
        op.execute(f"CREATE TRIGGER protect_recovery_rows BEFORE UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION protect_monitor_history()")
        op.execute(f"CREATE TRIGGER protect_recovery_truncate BEFORE TRUNCATE ON {table} FOR EACH STATEMENT EXECUTE FUNCTION protect_monitor_history()")


def downgrade():
    if (context.get_x_argument(as_dictionary=True).get("allow_data_loss") != "true"
            and not context.config.attributes.get("allow_data_loss", False)):
        raise RuntimeError("Recovery dispatch downgrade deletes history; requires disposable data and allow_data_loss=true")
    for table in reversed(TABLES):
        op.drop_table(table)
