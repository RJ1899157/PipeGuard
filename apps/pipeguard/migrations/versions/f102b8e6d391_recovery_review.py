"""Immutable review-only recovery proposals and human decisions.

Revision ID: f102b8e6d391
Revises: e7c2b936a410
"""
from alembic import context, op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "f102b8e6d391"
down_revision = "e7c2b936a410"
branch_labels = None
depends_on = None


def record_columns():
    return [sa.Column("id", sa.Uuid(), primary_key=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now())]


def upgrade():
    op.create_table("recovery_proposals",
        sa.Column("incident_id", sa.Uuid(), sa.ForeignKey("incidents.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("bundle_id", sa.Uuid(), sa.ForeignKey("evidence_bundles.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("request_key", sa.Uuid(), nullable=False, unique=True),
        sa.Column("actor", sa.String(40), nullable=False),
        sa.Column("payload", JSONB(), nullable=False),
        sa.Column("payload_hash", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False), *record_columns(),
        sa.CheckConstraint("payload_hash ~ '^[0-9a-f]{64}$'", name="sha256_hex"),
        sa.CheckConstraint("jsonb_typeof(payload) = 'object' AND octet_length(payload::text) <= 16384", name="bounded_payload"),
        sa.CheckConstraint("expires_at > created_at AND expires_at <= created_at + interval '10 minutes'", name="expiry"))
    op.create_index("ix_recovery_proposals_incident", "recovery_proposals", ["incident_id", "created_at", "id"])
    op.create_table("recovery_decisions",
        sa.Column("proposal_id", sa.Uuid(), sa.ForeignKey("recovery_proposals.id", ondelete="RESTRICT"), nullable=False, unique=True),
        sa.Column("request_key", sa.Uuid(), nullable=False, unique=True),
        sa.Column("proposal_hash", sa.String(64), nullable=False),
        sa.Column("decision", sa.String(10), nullable=False),
        sa.Column("actor", sa.String(40), nullable=False), *record_columns(),
        sa.CheckConstraint("proposal_hash ~ '^[0-9a-f]{64}$'", name="sha256_hex"),
        sa.CheckConstraint("decision IN ('approve', 'reject')", name="decision"))
    for table in ("recovery_proposals", "recovery_decisions"):
        op.execute(f"CREATE TRIGGER protect_recovery_rows BEFORE UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION protect_monitor_history()")
        op.execute(f"CREATE TRIGGER protect_recovery_truncate BEFORE TRUNCATE ON {table} FOR EACH STATEMENT EXECUTE FUNCTION protect_monitor_history()")


def downgrade():
    if (context.get_x_argument(as_dictionary=True).get("allow_data_loss") != "true"
            and not context.config.attributes.get("allow_data_loss", False)):
        raise RuntimeError("Recovery audit downgrade deletes history; requires disposable data and allow_data_loss=true")
    op.drop_table("recovery_decisions")
    op.drop_table("recovery_proposals")
