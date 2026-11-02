"""Append-only investigation requests and terminal outcomes.

Revision ID: e7c2b936a410
Revises: bd47c5a01e29
"""
from alembic import context, op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "e7c2b936a410"
down_revision = "bd47c5a01e29"
branch_labels = None
depends_on = None


def record_columns():
    return [sa.Column("id", sa.Uuid(), primary_key=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now())]


def upgrade():
    op.create_table("investigation_requests",
        sa.Column("bundle_id", sa.Uuid(), sa.ForeignKey("evidence_bundles.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("request_key", sa.Uuid(), nullable=False, unique=True),
        sa.Column("actor", sa.String(40), nullable=False),
        sa.Column("model", sa.String(100), nullable=False),
        sa.Column("prompt_version", sa.String(60), nullable=False),
        sa.Column("input_payload", JSONB(), nullable=False),
        sa.Column("input_hash", sa.String(64), nullable=False),
        *record_columns(),
        sa.CheckConstraint("input_hash ~ '^[0-9a-f]{64}$'", name="sha256_hex"),
        sa.CheckConstraint("jsonb_typeof(input_payload) = 'object' AND octet_length(input_payload::text) <= 32768", name="bounded_input"))
    op.create_index("ix_investigation_requests_created", "investigation_requests", ["created_at", "id"])
    op.create_index("ix_investigation_requests_bundle", "investigation_requests", ["bundle_id", "created_at", "id"])
    op.create_table("investigation_outcomes",
        sa.Column("request_id", sa.Uuid(), sa.ForeignKey("investigation_requests.id", ondelete="RESTRICT"), nullable=False, unique=True),
        sa.Column("state", sa.String(20), nullable=False),
        sa.Column("payload", JSONB(), nullable=False),
        *record_columns(),
        sa.CheckConstraint("state IN ('completed', 'failed')", name="state"),
        sa.CheckConstraint("jsonb_typeof(payload) = 'object' AND octet_length(payload::text) <= 16384", name="bounded_output"))
    for table in ("investigation_requests", "investigation_outcomes"):
        op.execute(f"CREATE TRIGGER protect_investigation_rows BEFORE UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION protect_monitor_history()")
        op.execute(f"CREATE TRIGGER protect_investigation_truncate BEFORE TRUNCATE ON {table} FOR EACH STATEMENT EXECUTE FUNCTION protect_monitor_history()")


def downgrade():
    if (context.get_x_argument(as_dictionary=True).get("allow_data_loss") != "true"
            and not context.config.attributes.get("allow_data_loss", False)):
        raise RuntimeError("Investigation audit downgrade deletes history; requires disposable data and allow_data_loss=true")
    op.drop_table("investigation_outcomes")
    op.drop_table("investigation_requests")
