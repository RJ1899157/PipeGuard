"""One monitored job per task: stable run identity and Airflow-native retry numbers."""
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess

from airflow.sdk import DAG, Param, get_current_context, task

ROOT=Path(__file__).resolve().parents[3]


@task(retries=1,retry_delay=timedelta(seconds=5),execution_timeout=timedelta(minutes=4))
def build_orders():
    context=get_current_context()
    identity="|".join((context["dag"].dag_id,context["run_id"],context["task"].task_id))
    run_id="airflow-"+sha256(identity.encode()).hexdigest()
    # Pass only workload configuration; no Airflow metadata or API signing credentials.
    config=ROOT/"sample-pipelines/orders/.env"
    values=dict(line.split("=",1) for line in config.read_text().splitlines() if line and not line.startswith("#"))
    if not all(values.get(key) for key in ("PIPEGUARD_INTEGRATION_ID","PIPEGUARD_JOB_ID","PIPEGUARD_PRODUCER_TOKEN")):
        raise RuntimeError("Configure sample monitoring before starting the monitored DAG")
    allowed={"ORDERS_HOST","ORDERS_PORT","ORDERS_DATABASE","ORDERS_USER","ORDERS_SCHEMA_PREFIX",
             "DBT_ENV_SECRET_ORDERS_PASSWORD","PIPEGUARD_INTEGRATION_ID","PIPEGUARD_JOB_ID",
             "PIPEGUARD_PRODUCER_TOKEN","PIPEGUARD_BASE_URL"}
    environment={key:value for key,value in os.environ.items() if key in ("PATH","HOME","LANG","LC_ALL","TMPDIR")}
    environment.update({key:value for key,value in values.items() if key in allowed})
    environment["DBT_SEND_ANONYMOUS_USAGE_STATS"]="false"
    executable=ROOT/"sample-pipelines/orders/.venv/bin/python"
    command=[str(executable),str(ROOT/"sample-pipelines/orders/run.py"),"--run-id",run_id,
             "--attempt",str(context["ti"].try_number)]
    if context["params"]["simulate_first_attempt_failure"]:
        command.append("--simulate-first-attempt-failure")
    result=subprocess.run(command,env=environment,capture_output=True,text=True,timeout=180,check=False)
    if result.returncode:
        # The workload has already persisted its bounded failure observation.
        raise RuntimeError("orders_workload_failed; inspect workload artifacts and PipeGuard attempts")
    summary=json.loads(result.stdout.strip().splitlines()[-1])
    return {key:summary[key] for key in ("external_run_id","attempt_number","dbt_succeeded","monitoring")}


with DAG("pipeguard_orders",start_date=datetime(2026,10,1,tzinfo=timezone.utc),schedule="@daily",
         catchup=False,max_active_runs=1,is_paused_upon_creation=True,
         default_args={"owner":"RJ1899157"},
         params={"simulate_first_attempt_failure":Param(False,type="boolean")},
         tags=["pipeguard","synthetic","orders"]) as dag:
    build_orders()
