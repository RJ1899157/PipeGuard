# Stage 7 verification — 2026-10-31

## Automated checks

- Monitoring/PostgreSQL suite: **188 passing tests**.
- Independent orders workload: **45 passing tests**.
- Alembic reports no model/schema drift at revision `a71e3fbc477c`.
- Existing source-role, authentication, replay, retry-history, failure-permutation, termination and incident tests remain included.
- The upstream Starlette/HTTPX test-client deprecation warning remains; no dependency was installed solely to silence it.

| Area | Verified scenarios |
| --- | --- |
| Receipt | Exact replay; conflicting payload/event key; OpenLineage UUID binding reuse; logical-step identity collision; atomic rollback of catalog/edges on failure |
| Validation | Extra fields, SQL/facets, credential/query-bearing namespaces, oversized dataset arrays, duplicate datasets, boolean schema version and inconsistent partial reasons rejected without input echo |
| Scope | Integration-scoped receipt, source reads, graph and evidence; shared dataset identity does not expose another integration's edges; forged cross-scope evidence references excluded |
| History | All six orders of START/COMPLETE/OTHER metadata; source-time and receipt-time cutoffs; old snapshots unchanged after new execution failures; repeated reopen/recovery episodes retain distinct lifecycle transitions |
| Traversal | Upstream/downstream/both, cycles, depth/node limits and explicit partial coverage; indexed relationships checked against source payloads; invalid stored source hash flagged |
| Completeness | Expected steps missing, unknown inventory, START-only reports, incomplete delivery, later complete recovery, contradictory terminal outcomes and complete absence after explicit grace |
| Evidence | Stable content hash and idempotent capture; prior failed and successful attempts retained; old cited evidence survives recent polling noise; >100 cited records produce bounded/truncated snapshots |
| Persistence | Owner/runtime UPDATE, DELETE and TRUNCATE denied for lineage identity, assertions, datasets and bundles; ordinary migration downgrade requires explicit data-loss permission |
| Sample adapter | Stable per-attempt UUIDs, exact artifact fingerprints, matching invocation identity, missing/invalid/mixed artifacts, unresolved dependencies, unsupported/ephemeral relations, skipped/unknown results, secret-marker exclusion and durable lineage replay |

The namespace network-fetch test confirms that ingestion treats even network-looking dataset identities as data. No runtime API fetches schemas, producer URLs, artifact URLs or dataset namespaces.

## Live local demonstration

`milestone_lineage_inventory` ran through native Airflow failure and retry:

- Airflow/PipeGuard execution succeeded without a reconciliation flag.
- Attempt 1 remained failed; attempt 2 remained successful.
- Nine lineage source events were retained: one early-failure metadata gap, plus START/COMPLETE for the loader and three dbt models on the retry.
- Attempt 2 produced **9 graph nodes** (5 datasets, 4 step executions), **8 links**, no truncation and `reported_complete` declared coverage.
- Both the execution-failure and lineage-partial incidents resolved from explicit later evidence.
- A live evidence bundle preserved both attempts, referenced lineage, validated its content hash and remained untruncated. It correctly retained `partial_lineage` for the failed attempt; it did not invent that attempt's missing model metadata.
- All **18** nested events from the two lineage demonstrations validated against the official OpenLineage 2.0.2 JSON schema with format checking. Validation used an already isolated environment; no monitoring/workload packages were installed globally.
- Both existing jobs were enrolled for execution monitoring. Live coverage reported **zero unmonitored jobs**. The orders job also has an explicit lineage-delivery expectation; the legacy synthetic API check remains explicitly event-only.
- The sample DAG was returned to paused state after the controlled demonstration.

## Limits

This verifies the bounded table-level profile and local sample. It does not certify universal dependency discovery, full OpenLineage/facet interoperability, data correctness, production scale, cryptographic provenance, or autonomous investigation/recovery. Old reports lacking step inventories remain explicitly incomplete. Missing metadata before instrumentation cannot be reconstructed as if it had been observed.

See [architecture](architecture/lineage-evidence.md) and [failure coverage](failure-coverage.md) for the full scope and residual operational requirements.
