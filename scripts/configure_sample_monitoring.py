"""Provision an integration-scoped sample producer without sharing admin credentials."""
import os
from pathlib import Path
import httpx


def main():
    path=Path(__file__).resolve().parents[1] / "sample-pipelines/orders/.env"
    if not path.is_file() or path.is_symlink():
        raise RuntimeError("Configure the sample warehouse first")
    values=dict(line.split("=",1) for line in path.read_text().splitlines() if line and not line.startswith("#"))
    if values.get("PIPEGUARD_PRODUCER_TOKEN"):
        print("Sample producer already configured; left unchanged")
        return
    with httpx.Client(base_url="http://127.0.0.1:8000", headers={"Authorization":"Bearer "+os.environ["PIPEGUARD_ADMIN_TOKEN"]}, timeout=10, trust_env=False) as client:
        response=client.post("/v1/integrations",json={"name":"orders-airflow", "environment":"local", "kind":"airflow"})
        if response.status_code==409:
            offset=0
            while True:
                page=client.get("/v1/integrations",params={"limit":100,"offset":offset})
                page.raise_for_status()
                integration=next((x for x in page.json()["items"] if x["name"]=="orders-airflow" and x["environment"]=="local"),None)
                if integration or not page.json()["has_more"]:
                    break
                offset+=100
            if not integration or not integration["enabled"]:
                raise RuntimeError("Configured producer unavailable")
        else:
            response.raise_for_status()
            integration=response.json()
        response=client.post("/v1/jobs",json={"integration_id":integration["id"],"namespace":"local-orders", "name":"orders-pipeline", "kind":"job"})
        if response.status_code==409:
            offset=0
            while True:
                page=client.get("/v1/jobs",params={"limit":100,"offset":offset})
                page.raise_for_status()
                job=next((x for x in page.json()["items"] if x["integration_id"]==integration["id"] and x["namespace"]=="local-orders" and x["name"]=="orders-pipeline"),None)
                if job or not page.json()["has_more"]:
                    break
                offset+=100
            if job is None:
                raise RuntimeError("Configured job unavailable")
        else:
            response.raise_for_status()
            job=response.json()
        credential=client.post(f"/v1/integrations/{integration['id']}/credentials")
        credential.raise_for_status()
        values.update(PIPEGUARD_INTEGRATION_ID=integration["id"], PIPEGUARD_JOB_ID=job["id"],
                      PIPEGUARD_PRODUCER_TOKEN=credential.json()["token"], PIPEGUARD_BASE_URL="http://127.0.0.1:8000")
    temp=path.with_name(".env.monitor-tmp")
    descriptor=os.open(temp,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    try:
        with os.fdopen(descriptor,"w") as stream:
            stream.write("".join(f"{key}={value}\n" for key,value in values.items()))
        temp.replace(path)
    finally:
        temp.unlink(missing_ok=True)
    print("Scoped sample producer configured; token saved privately without displaying it")


if __name__=="__main__":
    try:
        main()
    except Exception:
        raise SystemExit("Sample monitoring provisioning failed (private details withheld)")
