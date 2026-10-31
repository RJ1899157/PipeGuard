"""Prepare only the restricted database credential for the independent local watchdog."""
import os
from pathlib import Path
import secrets

import psycopg
from psycopg import sql
from sqlalchemy.engine import make_url

from local_files import read_private, write_private
from run_watchdog import database_parameters


def main():
    root = Path(__file__).resolve().parents[1]
    path = root / ".env"
    values = dict(line.split("=", 1) for line in read_private(path, 65536).decode().splitlines()
                  if line and not line.startswith("#"))
    owner = make_url(os.environ["PIPEGUARD_DATABASE_URL"])
    if (owner.host not in {"127.0.0.1", "localhost"} or owner.database != "pipeguard"
            or owner.drivername != "postgresql+psycopg" or owner.query):
        raise ValueError("Dedicated local project database required")
    password = values.get("PIPEGUARD_WATCHDOG_PASSWORD") or secrets.token_hex(32)
    with psycopg.connect(host=owner.host, port=owner.port or 5432, dbname="pipeguard", user="postgres",
                         password=os.environ["POSTGRES_PASSWORD"], connect_timeout=5, autocommit=True) as connection:
        if connection.execute("""SELECT 1 FROM pg_auth_members m JOIN pg_roles r ON r.oid=m.member
            WHERE r.rolname='pipeguard_watchdog'""").fetchone():
            raise RuntimeError("Watchdog role must not have memberships")
        exists = connection.execute("SELECT 1 FROM pg_roles WHERE rolname='pipeguard_watchdog'").fetchone()
        operation = "ALTER ROLE" if exists else "CREATE ROLE"
        connection.execute(sql.SQL(operation + " {} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS CONNECTION LIMIT 3 PASSWORD {}").format(
            sql.Identifier("pipeguard_watchdog"), sql.Literal(password)))
        connection.execute("ALTER ROLE pipeguard_watchdog SET default_transaction_read_only=on")
        connection.execute("REVOKE ALL ON DATABASE pipeguard FROM pipeguard_watchdog")
        connection.execute("GRANT CONNECT ON DATABASE pipeguard TO pipeguard_watchdog")
        connection.execute("REVOKE ALL ON DATABASE airflow, sample_warehouse FROM pipeguard_watchdog")
        # This is the project's dedicated server. System databases remain usable
        # by postgres; application roles must connect only to their own database.
        connection.execute("REVOKE CONNECT, TEMPORARY ON DATABASE postgres, template1 FROM PUBLIC")
        connection.execute("REVOKE ALL ON SCHEMA public FROM pipeguard_watchdog")
        connection.execute("GRANT USAGE ON SCHEMA public TO pipeguard_watchdog")
        connection.execute("REVOKE ALL ON ALL TABLES IN SCHEMA public FROM pipeguard_watchdog")
        connection.execute("REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM pipeguard_watchdog")
        connection.execute("GRANT SELECT ON jobs, monitor_policies, monitor_heartbeats TO pipeguard_watchdog")
    values["PIPEGUARD_WATCHDOG_PASSWORD"] = password
    write_private(path, "".join(f"{key}={value}\n" for key, value in values.items()))
    value = owner.set(username="pipeguard_watchdog", password=password).render_as_string(hide_password=False)
    database_parameters(value)
    target = root / ".env.watchdog"
    write_private(target, "PIPEGUARD_WATCHDOG_DATABASE_URL=" + value + "\n")
    print("Private local watchdog configuration prepared")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        raise SystemExit("Watchdog configuration failed (private details withheld)")
