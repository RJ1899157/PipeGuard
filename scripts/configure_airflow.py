"""Provision the local orchestrator database and private, loopback-only configuration."""
import base64
import json
import os
from pathlib import Path
import secrets
import sys
from local_files import ensure_private_directory, read_private, write_private

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"apps/pipeguard/src"))
import psycopg
from psycopg import sql
from pipeguard.db.config import database_url


def provision_users(path):
    exists = path.exists()
    users = json.loads(read_private(path, 65536)) if exists else {}
    if not isinstance(users, dict) or any(
        not isinstance(value, str) or not value or len(value) > 2048 for value in users.values()
    ):
        raise ValueError("Invalid private Airflow user configuration")
    names = ("RJ1899157", "pipeguard_observer", "pipeguard_recovery")
    if any(name not in users for name in names):
        for name in names:
            if name not in users:
                users[name] = secrets.token_urlsafe(32)
        # Preseed every configured account: Airflow must never generate and print
        # a missing account password at server startup.
        write_private(path, json.dumps(users), exclusive=not exists)


def main():
    root=Path(__file__).resolve().parents[1]
    home=root/"data/local/airflow"
    ensure_private_directory(home)
    private=root/".env.airflow"
    if private.is_symlink():
        raise RuntimeError("Configuration must be a regular file")
    previous=dict(line.split("=",1) for line in read_private(private,65536).decode().splitlines() if line and not line.startswith("#")) if private.exists() else {}
    password=previous.get("AIRFLOW_LOCAL_DB_PASSWORD") or secrets.token_hex(32)
    owner=database_url()
    if owner.host not in ("127.0.0.1","localhost") or owner.database!="pipeguard":
        raise RuntimeError("Local database required")
    with psycopg.connect(host=owner.host,port=owner.port or 5432,dbname="postgres",user="postgres",password=os.environ["POSTGRES_PASSWORD"],autocommit=True) as connection:
        exists=connection.execute("SELECT 1 FROM pg_roles WHERE rolname='airflow_owner'").fetchone()
        operation="ALTER ROLE" if exists else "CREATE ROLE"
        connection.execute(sql.SQL(operation+" {} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS PASSWORD {}").format(sql.Identifier("airflow_owner"),sql.Literal(password)))
        database=connection.execute("SELECT pg_get_userbyid(datdba) FROM pg_database WHERE datname='airflow'").fetchone()
        if database is None:
            connection.execute("CREATE DATABASE airflow OWNER airflow_owner")
        elif database[0]!="airflow_owner":
            raise RuntimeError("Unexpected metadata database owner")
        connection.execute("REVOKE ALL ON DATABASE airflow FROM PUBLIC, pipeguard_api, sample_orders")
        connection.execute("REVOKE ALL ON DATABASE pipeguard, sample_warehouse FROM airflow_owner")
    password_file=home/"users.json"
    provision_users(password_file)
    values={
        "AIRFLOW_LOCAL_DB_PASSWORD":password,"AIRFLOW_HOME":str(home),
        "AIRFLOW__DATABASE__SQL_ALCHEMY_CONN":owner.set(username="airflow_owner",password=password,database="airflow",drivername="postgresql+psycopg2").render_as_string(hide_password=False),
        "AIRFLOW__CORE__DAGS_FOLDER":str(root/"infra/airflow/dags"),
        "AIRFLOW__CORE__LOAD_EXAMPLES":"False","AIRFLOW__CORE__EXECUTOR":"LocalExecutor",
        "AIRFLOW__CORE__PARALLELISM":"1","AIRFLOW__CORE__MAX_ACTIVE_TASKS_PER_DAG":"1",
        "AIRFLOW__CORE__MAX_ACTIVE_RUNS_PER_DAG":"1","AIRFLOW__API__HOST":"127.0.0.1",
        "AIRFLOW__CORE__EXECUTION_API_SERVER_URL":"http://127.0.0.1:8080/execution/",
        "AIRFLOW__CORE__AUTH_MANAGER":"pipeguard_airflow_auth.PipeGuardAuthManager",
        "AIRFLOW__CORE__SIMPLE_AUTH_MANAGER_USERS":"RJ1899157:admin,pipeguard_observer:viewer,pipeguard_recovery:viewer",
        "AIRFLOW__CORE__SIMPLE_AUTH_MANAGER_ALL_ADMINS":"False",
        "PIPEGUARD_AIRFLOW_RECOVERY_ENABLED":"0",
        "PIPEGUARD_AIRFLOW_MANUAL_ONLY":previous.get("PIPEGUARD_AIRFLOW_MANUAL_ONLY","0"),
        "AIRFLOW__CORE__SIMPLE_AUTH_MANAGER_PASSWORDS_FILE":str(password_file),
        "AIRFLOW__API_AUTH__JWT_SECRET":previous.get("AIRFLOW__API_AUTH__JWT_SECRET") or secrets.token_urlsafe(32),
        "AIRFLOW__CORE__FERNET_KEY":previous.get("AIRFLOW__CORE__FERNET_KEY") or base64.urlsafe_b64encode(secrets.token_bytes(32)).decode(),
        "AIRFLOW__DAG_PROCESSOR__REFRESH_INTERVAL":"5","AIRFLOW__DAG_PROCESSOR__MIN_FILE_PROCESS_INTERVAL":"5",
        "AIRFLOW__SCHEDULER__ENABLE_HEALTH_CHECK":"False","OBJC_DISABLE_INITIALIZE_FORK_SAFETY":"YES",
        "AIRFLOW__CORE__DEFAULT_TIMEZONE":"utc",
    }
    write_private(private,"".join(f"{key}={value}\n" for key,value in values.items()))
    print("Airflow metadata database and private local configuration prepared")


if __name__=="__main__":
    try:
        main()
    except Exception:
        raise SystemExit("Airflow provisioning failed (private details withheld)")
