# Monitored sample pipelines

Independent workloads whose execution and data quality PipeGuard will observe.
Business rows, transformations, credentials and workload dependencies stay separate
from the monitoring application.

- [Orders](orders/README.md): validated synthetic CSV ingestion, dbt staging/marts,
  quality checks, repeatable builds and controlled failure verification.

The orders workload currently runs independently. Event reporting and Airflow
orchestration are the next integration milestone.
