"""Provision the independent local sample database and private workload configuration."""
import os
from pathlib import Path
import secrets
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps/pipeguard/src"))
import psycopg
from psycopg import sql
from pipeguard.db.config import database_url


def main():
    root = Path(__file__).resolve().parents[1]
    target = root / "sample-pipelines/orders/.env"
    if target.is_symlink():
        raise RuntimeError("Configuration must be a regular file")
    values = {}
    if target.exists():
        values = dict(line.split("=", 1) for line in target.read_text().splitlines() if line and not line.startswith("#"))
    password = values.get("DBT_ENV_SECRET_ORDERS_PASSWORD") or secrets.token_hex(32)
    owner = database_url()
    if owner.host not in ("127.0.0.1", "localhost") or owner.database != "pipeguard":
        raise RuntimeError("Sample provisioning requires the local development database")
    with psycopg.connect(host=owner.host, port=owner.port or 5432, dbname="postgres",
                         user="postgres", password=os.environ["POSTGRES_PASSWORD"], autocommit=True) as connection:
        exists = connection.execute("SELECT 1 FROM pg_roles WHERE rolname = 'sample_orders'").fetchone()
        operation = "ALTER ROLE" if exists else "CREATE ROLE"
        connection.execute(sql.SQL(operation + " {} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS PASSWORD {}").format(sql.Identifier("sample_orders"), sql.Literal(password)))
        database = connection.execute("SELECT pg_get_userbyid(datdba) FROM pg_database WHERE datname = 'sample_warehouse'").fetchone()
        if database is None:
            connection.execute("CREATE DATABASE sample_warehouse OWNER sample_orders")
        elif database[0] != "sample_orders":
            raise RuntimeError("Existing sample database has an unexpected owner")
        connection.execute("REVOKE ALL ON DATABASE sample_warehouse FROM PUBLIC")
        connection.execute("REVOKE ALL ON DATABASE sample_warehouse FROM pipeguard_api")
        connection.execute("REVOKE ALL ON DATABASE pipeguard FROM sample_orders")
    values.update(ORDERS_HOST=owner.host, ORDERS_PORT=str(owner.port or 5432),
                  ORDERS_DATABASE="sample_warehouse", ORDERS_USER="sample_orders",
                  DBT_ENV_SECRET_ORDERS_PASSWORD=password, DBT_SEND_ANONYMOUS_USAGE_STATS="false")
    temp = target.with_name(".env.warehouse-tmp")
    descriptor = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "w") as stream:
            stream.write("".join(f"{key}={value}\n" for key, value in values.items()))
        temp.replace(target)
    finally:
        temp.unlink(missing_ok=True)
    print("Independent sample database configured; only workload credentials saved in sample .env")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        raise SystemExit("Sample database provisioning failed; check local configuration (details withheld)")
