"""Index scoped monitoring reads without changing or deleting retained evidence.

Revision ID: bd47c5a01e29
Revises: a71e3fbc477c
"""
from alembic import op
import sqlalchemy as sa

revision = "bd47c5a01e29"
down_revision = "a71e3fbc477c"
branch_labels = None
depends_on = None


def upgrade():
    op.create_index("ix_runs_job_created", "runs", ["job_id", "created_at", "id"])
    op.create_index("ix_events_integration_job", "ingested_events", ["integration_id", sa.text("(payload ->> 'job_id')")])
    op.create_index("ix_observations_job_kind_created", "observations", ["job_id", "kind", "created_at", "occurred_at", "id"])
    op.create_index("ix_observations_quality_scope", "observations", ["job_id", sa.text("(payload ->> 'external_run_id')"),
        sa.text("((payload ->> 'attempt_number')::integer)"), "created_at", "id"],
        postgresql_where=sa.text("source = 'quality' AND kind = 'quality_report'"))
    op.create_index("ix_observations_airflow_run", "observations", ["job_id", sa.text("(payload ->> 'external_run_id')"),
        "created_at", "occurred_at", "id"], postgresql_where=sa.text("source = 'airflow' AND kind = 'airflow_run'"))
    op.create_index("ix_incidents_created", "incidents", [sa.text("created_at DESC"), "id"])
    op.create_index("ix_incident_history_received", "incident_history", ["incident_id", "created_at", "id"])


def downgrade():
    # Removing indexes changes performance only; source and incident history remain intact.
    for table, name in [("incident_history", "ix_incident_history_received"), ("incidents", "ix_incidents_created"),
        ("observations", "ix_observations_airflow_run"), ("observations", "ix_observations_quality_scope"),
        ("observations", "ix_observations_job_kind_created"), ("ingested_events", "ix_events_integration_job"),
        ("runs", "ix_runs_job_created")]:
        op.drop_index(name, table_name=table)
