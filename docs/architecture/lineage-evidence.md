# Lineage and evidence architecture

## Implemented boundary

PipeGuard accepts a bounded **OpenLineage 2.0.2 RunEvent profile** inside an authenticated PipeGuard envelope. This is an initial table/dataset-level integration, not a general OpenLineage server. JobEvent, DatasetEvent, arbitrary facets, SQL text, column lineage, row-level flow and arbitrary external producer URLs are not supported by this profile. Unsupported fields are rejected rather than retained as unreviewed evidence.

The orders adapter reads the full-build dbt manifest and matching run results. It reports logical CSV input → raw orders → staging → orders mart → daily revenue. Loader boundaries are producer-reported; dbt links are declared dependencies from the manifest. A COMPLETE event reports a step outcome; it does not prove that every output row is correct or that the warehouse changed atomically.

No additional service, cloud credential, or application dependency is required. Marquez remains deferred. The local adapter emits standard JSON using existing environments. The nested live events were separately validated against the official OpenLineage schema using the already isolated Airflow environment.

## Identity and receipt

- `lineage_runs` explicitly binds an OpenLineage UUID and logical step to a monitored job, external execution ID and attempt. UUID reuse with a different binding, or a new UUID for the same step/attempt binding, is rejected and audited.
- `lineage_events` stores canonical validated envelopes, source time, receipt time and SHA-256. Event keys are integration-scoped. Exact replay returns the existing UUID; conflicting reuse records a durable hash-only delivery-conflict observation and returns 409.
- `datasets` identifies datasets by `(namespace, name)`. Shared identity does not grant access to another integration's events or edges.
- `dataset_mentions` indexes input/output assertions by immutable source event. Dataset → step execution → dataset is a bipartite graph; inputs are not multiplied into unsupported pairwise data-flow claims.
- Source receipt, binding, catalog insertion and mentions commit together. Failure rolls back all of them. Read APIs verify indexed edges against the source payload and mark hash or projection mismatches incomplete.
- Lineage events never silently change the execution-state projection or approve recovery. Execution and lineage evidence remain independently attributable.

Ordinary database updates, deletion and truncation of lineage bindings, source events, dataset identity, mentions, expectations and bundles are blocked by triggers. The runtime has explicit SELECT/INSERT grants without UPDATE/DELETE/TRUNCATE on these tables. Privileged database access can still forge evidence; these controls are not a cryptographic proof of truth.

## Completeness and missing metadata

Each event declares the expected logical step inventory for its execution attempt. Inventory disagreement, unknown inventory, missing expected steps, missing terminal step reports, unresolved dependencies, unsupported resources and partial artifacts remain visible. A single fully described step cannot prove a complete pipeline graph.

`lineage_expectations` explicitly requires complete delivery within a grace period after a terminal attempt. It applies to **newly observed run records** created after enrollment, so enrollment does not invent historical metadata for old executions. Newly discovered/backfilled historical runs after enrollment are still subject to the expectation. The orders job is enrolled; the legacy event-only synthetic job has no data-transformation lineage expectation.

Deterministic conditions:

- `lineage_missing`: the enrolled execution has not supplied a complete declared inventory by its deadline.
- `lineage_partial`: received metadata is incomplete, its declared inventory is incomplete, or integrity checks fail.
- `lineage_conflict`: the same logical step run reports contradictory terminal states; it remains open for investigation.

Later explicit complete metadata can recover a gap. A successful execution alone cannot. Earlier partial reports remain stored and the historical union still identifies them. If a process dies before sending lineage, independent execution detection still works and the lineage expectation identifies missing metadata.

## Historical graph semantics

`GET /v1/jobs/{job_id}/lineage` returns an **observed union**, not a claim about the latest deployed graph. START, COMPLETE and OTHER metadata are additive. Old dependencies are not deleted when a later execution declares different ones.

Use external-run and attempt filters to inspect one execution. `as_of` bounds source event time; `known_at` bounds receipt time. These answer different questions: what a source says happened by a time, and what PipeGuard actually knew then. Late delivery cannot rewrite an older knowledge cutoff.

Traversal supports upstream, downstream or both, including cycles. Defaults and hard bounds are explicit: at most 1,000 source events, depth 1–12, 200 returned nodes, 1,000 returned links and 100 source references per link. Hitting a bound returns partial/truncated coverage. If a requested root is outside a capped scan, the API returns an explicit scan-limit error rather than claiming the dataset does not exist. Narrow the execution/time scope to inspect more history.

`reported_complete` means the retained events satisfy their producer-declared inventory within this query. It is not proof that every intended business dependency was instrumented.

## Incident evidence snapshots

`evidence_bundles` captures a bounded, immutable, versioned incident snapshot using PostgreSQL REPEATABLE READ. The snapshot includes scoped execution attempts, original execution receipts, quality/source observations, lineage events, history references and explicit missing-evidence reasons.

Cited original evidence has priority over recent context, so old failures are not lost among repeated healthy polling snapshots. Source-health context includes the latest coverage records. Run-specific incidents select their execution; job-wide incidents explicitly label their broader context. Cross-job, malformed, missing or unsupported references are flagged and never followed into another integration's data.

Snapshots contain at most 100 evidence items and 512 KiB of serialized item content. Larger or missing context is marked incomplete. Repeated capture of identical content reuses the snapshot ID; later evidence produces another snapshot without modifying the old one. Captures may be retried after a database conflict; no partial bundle is committed.

Every item names its table/UUID, summary and hash basis. `summary_v1` hashes the allowlisted summary; `source_content_v1` hashes canonical stored source content (or the selected canonical history fields). Execution and lineage source hashes are checked before claims are included. Bundle SHA-256 covers its canonical payload, excluding its database capture timestamp. Hashes establish content consistency, not source honesty or verified causation.

Manual advisory investigation and bounded human-authorized recovery now consume these snapshots. Metadata identifiers remain untrusted data; model output cannot authorize an action. See the [investigation contract](../investigation-operations.md) and [live recovery acceptance](../recovery-live-verification.md).

## Compatibility references

- [OpenLineage object model](https://openlineage.io/docs/spec/object-model/)
- [OpenLineage 2.0.2 schema](https://openlineage.io/spec/2-0-2/OpenLineage.json), independently downloaded and checked with SHA-256 `69f68bee00b9beac88a87059c0102410e7bb05f3f43c46d02a0409831eceb0d2`
- [dbt manifest](https://docs.getdbt.com/reference/artifacts/manifest-json)
- [dbt run results](https://docs.getdbt.com/reference/artifacts/run-results-json)
