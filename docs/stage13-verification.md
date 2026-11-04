# Stage 13 security, performance and debugging

Date: **2026-11-04**. Status: **bounded local gate verified**. Tested revision:
`d258ef37fd5466142a0b9101f4c9ba2c63e5137e`. [Structured evidence](audit/stage13-verification.json).
This stage does not replace Stage 14's final independent full-project audit.

## Implemented hardening

- API body admission now limits bytes, absolute read time and concurrent readers;
  timeout/overload/malformed-length responses are explicit and carry safe headers.
- Dashboard stream reads have an absolute deadline; a source that never completes
  cancellation cannot hold the request indefinitely.
- Graph construction streams event batches, limits canonical payload bytes and
  scanned mentions, and admits two graph builders per worker after scope checks.
  Capacity-limited reads remain explicitly partial; source history is retained.
- Delivery verification checks the Node runtime selected by pnpm, not only the
  shell runtime, and exercises real HTTP body deadlines plus temporary API-database
  access loss/restoration on its own disposable cluster.
- The [threat model](security-threat-model.md) records assets, trust boundaries,
  controls, verification methods and deployment restrictions.

## Runtime security patches

[Python 3.12.16](https://www.python.org/downloads/release/python-31216/) and
[Node.js 22.23.4](https://nodejs.org/en/blog/release/v22.23.4) address security
issues in the previously installed interpreters. The three application environments
were recreated with the same locked package versions under Python 3.12.16.
The dashboard uses a verified project-local Node.js archive; system runtimes were
not replaced. Original environments are preserved privately for rollback.
uv 0.13.7 installs the pinned Python runtime; CI reads both runtime version files.
All 562 suite cases and the fresh-export acceptance checks passed on these
patched runtimes. The installed package versions did not change.

## Measured graph evidence

A disposable schema contains 1,000 valid lineage events and 64,000 dataset mentions.
The controlled comparison below used Python 3.12.15 for both versions.
Three warm runs before the change have median 1,701.73 ms. The current bounded
implementation has median 494.39 ms. A separate tracemalloc run records peak Python
allocations of 220,805,401 bytes before and 59,583,616 after. The mention query
fetches 10,001 rows (including the overflow sentinel), rather than 64,000.

Both versions return at most 200 nodes/1,000 links and report partial coverage.
The new result can contain fewer assertions because scanning stops earlier; this
is a resource-bound tradeoff, not a claim that a complete graph became equivalent
and faster. Tracemalloc is not process RSS, and local warm samples are not a
throughput or distributed-deployment guarantee. No retained evidence was deleted. A follow-up on Python 3.12.16 recorded a
419.55 ms median and 59,583,040 traced peak bytes; it is a separate runtime sample.

## Current dependency findings

Fresh OSV queries find no known matches in the installed application (28), workload
(65) or Airflow (131) package entries; pnpm reports zero known matches across its
86 recorded dependency entries. The container still matches 130 source advisories;
no matched record publishes a nonzero compatible fixed version. One GnuTLS
entry is absent from the bulk feed, but its [individual tracker page](https://security-tracker.debian.org/tracker/CVE-2026-95209)
still lists trixie as vulnerable/unfixed, with disputed security impact. That
discrepancy is retained rather than dropping the advisory. The official ARM64
image is unchanged. These are time-specific results.

## Acceptance results

- **562 suite cases passed:** 437 backend, 48 frontend, 64 workload and 13 Airflow.
  The existing Starlette/HTTPX test-client deprecation warning remains unsuppressed.
- Fresh committed-export checks passed migrations, stored-contract equality,
  dependency consistency, strict TypeScript/unused rules, formatting, production
  build and HTTP startup. Exact Node 22.23.4 was checked through pnpm.
- Actual isolated HTTP requests returned 413 for an oversized declared length
  without a body, and 408 for a stalled body. Admission responses were no-store.
- The orders workload failed once and retried successfully. Both attempts,
  incident transitions and unchanged captured evidence remained. Its 14 quality
  checks passed and successful-attempt lineage reported complete.
- Denying only the disposable cluster's API account preserved liveness 200 while
  readiness returned sanitized 503. Restoring access returned readiness to 200
  and evidence was unchanged. This is an access outage, not physical host loss.
- New backups of all three databases passed disposable restore verification.
  Inspection found no remaining restore-check databases. Backups remain on this disk.
- The retained API/dashboard, monitor, Airflow and watchdog use patched runtimes; live/ready/dashboard returned 200,
  live OpenAPI matched the stored contract and all four listeners stayed on loopback.
- All **7,688** captured rows retained IDs and full native-row content hashes.
  Source inventory is **8 runs / 14 attempts**, recovery ledger **1/1/1/2** and
  investigation ledger **16/16**, unchanged. Recovery is off and the DAG paused.
- Before the runtime switch, twelve retained reads per route had local medians 2.91 ms (jobs), 3.16 ms (runs),
  3.11 ms (incidents), 5.12 ms (coverage). These are post-change samples, not a
  controlled causal comparison or interactive browser-performance claim.

The delivery runner removed its temporary stack; graph fixtures removed their
unique schemas. The catchable-termination drill remains recorded in [Stage 12](delivery-verification.md).

## Remaining gates and risks

Stage 14's independent multi-agent full-project audit remains required. The owner
started [run #3](https://github.com/RJ1899157/PipeGuard/actions/runs/41818080465) against `0dc22d91dd26c0d7978cb8f610a4f48b0e4ba709`;
both hosted Linux jobs passed. Actor and triggering actor are RJ1899157. Automatic
triggers remain disabled. Old run 41809107524 remains stuck: GitHub rejected
deletion with 403 and both cancellation endpoints with 409. Its administrative
cleanup remains unresolved; it is not the acceptance run.

Container advisories, the bulk-feed discrepancy, same-host monitoring, same-disk
backups, broader live AI evaluation and deployment/atomic-publication limits stay
open. Passing this gate does not establish universal optimality, zero vulnerabilities,
public deployment readiness or coverage of every possible failure. No new hosted-AI
generation or retained recovery run was performed.
