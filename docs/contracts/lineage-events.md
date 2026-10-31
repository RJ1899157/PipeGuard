# Lineage report v1

## Envelope and profile

`POST /v1/lineage-events` requires a scoped producer or administrator bearer token. Required envelope fields are integer `schema_version=1`, `event_id`, integration/job UUIDs, external run identity, positive integer attempt number, basis (`declared_dbt` or `producer_reported`), coverage (`complete` or `partial`) and nested `event`.

`expected_steps` contains up to 32 unique `{namespace, name}` identities. When supplied, the current event's step must be included. An empty inventory is accepted for incomplete/historical sources and explicitly yields unknown pipeline completeness. Inventories for an execution/attempt must agree to establish completeness. `missing_metadata` contains only supported machine codes; partial reports require reasons and complete step reports cannot contain them. Optional artifact hashes identify exact local manifest/run-results bytes without transmitting their content.

The nested event contains timezone-aware `eventTime`, producer `https://github.com/RJ1899157/PipeGuard`, schema URL `https://openlineage.io/spec/2-0-2/OpenLineage.json#/$defs/RunEvent`, one of START/RUNNING/COMPLETE/FAIL/ABORT/OTHER, `run.runId` UUID, logical `job` identity and explicit `inputs`/`outputs` arrays (up to 32 each). Duplicate dataset references within a role are rejected.

Dataset namespaces are identity strings, never network destinations. The profile rejects credentials, query strings, fragments and unsupported characters. Names are bounded identifiers. Facets, SQL, messages, row data and unknown fields are rejected without input echo. This profile does not accept every event an unconfigured OpenLineage SDK may emit; adapters must select compatible fields explicitly.

The shared HTTP body cap is 64 KiB. Normalized defaults, UTC timestamps and sorted compact JSON determine payload hashes. HTTP 202 means the event, identity binding, dataset catalog additions and edge assertions committed atomically. The response includes receipt UUID, replay status and processing state. Exact replay is idempotent. Event-content or run-identity collisions return 409 and retain a hash-only conflict signal. Ordinary source-history mutation is prohibited.

## Read and operational endpoints

| Route | Contract |
| --- | --- |
| `GET /v1/lineage-events/{id}` | Scoped normalized source payload, content hash and event/receipt times |
| `GET /v1/jobs/{id}/lineage` | Scoped observed union, provenance per link, explicit coverage and limits |
| `POST /v1/lineage-expectations` | Administrator enrollment: job UUID and bounded positive grace seconds |
| `GET /v1/jobs/{id}/lineage-expectation` | Scoped versioned expectation inspection |
| `POST /v1/incidents/{id}/evidence-bundles` | Scoped repeatable-read immutable capture; identical content reuses its ID |
| `GET /v1/evidence-bundles/{id}` | Scoped retained snapshot with hash and capture time |

Graph parameters: optional `external_run_id`, positive `attempt_number`, timezone-aware `as_of` and `known_at`, `root_dataset_id`, direction (`upstream`, `downstream`, `both`), depth 1–12 and node budget 1–200. A root must be visible in the job scope. Truncation and missing metadata are explicit. No route automatically fetches a dataset namespace, producer URL or schema URL.

Expectations are immutable and apply to run records created after enrollment. Complete absence and partial inventories do not count as healthy lineage. Existing execution policies and recovery approval boundaries are unchanged.

Machine-readable contract: [Lineage report schema](lineage-report-v1.schema.json) and [OpenAPI](http-api-v1.openapi.json). See [architecture](../architecture/lineage-evidence.md) for source authority and completeness semantics.
