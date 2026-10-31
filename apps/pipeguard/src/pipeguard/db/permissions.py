"""Explicit grants shared by local provisioning and isolated PostgreSQL checks."""
from sqlalchemy import text


def grant_runtime_access(connection, role="pipeguard_api", schema="public"):
    quote = connection.dialect.identifier_preparer.quote_identifier
    who, where = quote(role), quote(schema)
    connection.execute(text(f"GRANT USAGE ON SCHEMA {where} TO {who}"))
    for table in ("alembic_version", "integrations", "datasets", "jobs", "runs", "attempts", "ingested_events", "producer_credentials", "monitor_policies", "observations", "incidents", "incident_history", "monitor_heartbeats"):
        connection.execute(text(f"GRANT SELECT ON {where}.{quote(table)} TO {who}"))
    for table in ("integrations", "jobs", "runs", "attempts", "ingested_events", "producer_credentials", "monitor_policies", "observations", "incidents", "incident_history", "monitor_heartbeats"):
        connection.execute(text(f"GRANT INSERT ON {where}.{quote(table)} TO {who}"))
    for table in ("runs", "attempts", "incidents", "monitor_heartbeats"):
        connection.execute(text(f"GRANT UPDATE ON {where}.{quote(table)} TO {who}"))
    connection.execute(text(f"GRANT UPDATE (enabled) ON {where}.integrations TO {who}"))
    connection.execute(text(f"GRANT UPDATE (revoked) ON {where}.producer_credentials TO {who}"))
    connection.execute(text(f"GRANT UPDATE (processing_state, processing_error, processed_at) ON {where}.ingested_events TO {who}"))


def verify_runtime_access(connection):
    elevated = connection.scalar(text("""
        SELECT rolsuper OR rolcreatedb OR rolcreaterole OR rolbypassrls
        FROM pg_roles WHERE rolname = current_user
    """))
    schema_create = connection.scalar(text("SELECT has_schema_privilege(current_user, current_schema(), 'CREATE')"))
    owns_tables = connection.scalar(text("""
        SELECT EXISTS (SELECT 1 FROM pg_tables
        WHERE schemaname = current_schema() AND tableowner = current_user)
    """))
    memberships = connection.scalar(text("""
        SELECT EXISTS (SELECT 1 FROM pg_auth_members
        WHERE member = (SELECT oid FROM pg_roles WHERE rolname = current_user))
    """))
    if elevated or schema_create or owns_tables or memberships:
        raise RuntimeError("API requires a restricted database role without schema ownership")
    # Also fail early on a missing schema or missing basic runtime privileges.
    connection.execute(text("SELECT id FROM integrations LIMIT 0"))
    connection.execute(text("SELECT id FROM producer_credentials LIMIT 0"))
    revision = connection.scalar(text("SELECT version_num FROM alembic_version"))
    if revision != "fc50161412bd":
        raise RuntimeError("Apply the API schema migration before starting the server")
