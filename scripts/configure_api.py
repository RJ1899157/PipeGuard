"""Provision the local API role and private environment values without displaying secrets."""
import os
from pathlib import Path
import secrets
import sys
from local_files import write_private

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps/pipeguard/src"))
from psycopg import sql
from sqlalchemy import create_engine
from pipeguard.db.config import database_url
from pipeguard.db.permissions import grant_runtime_access


def main():
    root = Path(__file__).resolve().parents[1]
    path = root / ".env"
    if not path.is_file() or path.is_symlink():
        raise RuntimeError("Create a regular .env file first")
    owner_url = database_url()
    if owner_url.host not in ("127.0.0.1", "localhost") or owner_url.database != "pipeguard":
        raise RuntimeError("Local provisioning requires the local pipeguard database")
    values = dict(line.split("=", 1) for line in path.read_text().splitlines() if line and not line.startswith("#"))
    runtime_password = values.get("PIPEGUARD_API_PASSWORD") or secrets.token_hex(32)
    admin_token = values.get("PIPEGUARD_ADMIN_TOKEN") or secrets.token_urlsafe(32)
    runtime_url = owner_url.set(username="pipeguard_api", password=runtime_password)
    admin_url = owner_url.set(username="postgres", password=os.environ["POSTGRES_PASSWORD"])
    admin_engine = create_engine(admin_url, hide_parameters=True)
    owner_engine = create_engine(owner_url, hide_parameters=True)
    try:
        with admin_engine.begin() as connection:
            exists = connection.exec_driver_sql("SELECT 1 FROM pg_roles WHERE rolname = 'pipeguard_api'").first()
            statement = "ALTER ROLE" if exists else "CREATE ROLE"
            command = sql.SQL(statement + " {} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS PASSWORD {}").format(
                sql.Identifier("pipeguard_api"), sql.Literal(runtime_password))
            connection.connection.driver_connection.execute(command)
            connection.exec_driver_sql("GRANT CONNECT ON DATABASE pipeguard TO pipeguard_api")
        with owner_engine.begin() as connection:
            grant_runtime_access(connection)
        values.update(PIPEGUARD_API_PASSWORD=runtime_password, PIPEGUARD_ADMIN_TOKEN=admin_token,
                      PIPEGUARD_API_DATABASE_URL=runtime_url.render_as_string(hide_password=False))
        write_private(path, "".join(f"{key}={value}\n" for key, value in values.items()))
    finally:
        admin_engine.dispose()
        owner_engine.dispose()
    print("Local API role configured; credentials saved privately in .env")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        raise SystemExit("API provisioning failed; check local database configuration (details withheld)")
