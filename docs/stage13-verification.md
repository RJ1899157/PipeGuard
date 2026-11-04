# Stage 13 security, performance and debugging

Date: **2026-11-04**. Status: **in progress**. Focused backend checks pass;
complete committed-export verification and fresh restore drills are pending.
This stage does not replace Stage 14's final independent full-project audit.

## Changes under verification

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

## Preliminary measured graph evidence

A disposable schema contains 1,000 valid lineage events and 64,000 dataset mentions.
Three warm runs before the change have median 1,701.73 ms. The current bounded
implementation has median 494.39 ms. A separate tracemalloc run records peak Python
allocations of 220,805,401 bytes before and 59,583,616 after. The mention query
fetches 10,001 rows (including the overflow sentinel), rather than 64,000.

Both versions return at most 200 nodes/1,000 links and report partial coverage.
The new result can contain fewer assertions because scanning stops earlier; this
is a resource-bound tradeoff, not a claim that a complete graph became equivalent
and faster. Tracemalloc is not process RSS, and local warm samples are not a
throughput or distributed-deployment guarantee. No retained evidence was deleted.

## Current dependency findings

Fresh OSV queries find no known matches in the installed application (28), workload
(65) or Airflow (131) package entries; pnpm reports zero known matches across its
86 recorded dependency entries. The container still matches 130 source advisories;
full current Debian triage is being refreshed. These are time-specific results.

## Remaining acceptance work

- Complete the full fresh-export suites, build and real HTTP fault scenario.
- Verify new logical backups of all three databases through disposable restoration.
- Refresh retained services and verify health, disabled recovery and preserved history.
- Publish structured results and distinguish local acceptance from pending hosted CI.

The pending hosted run and checkpoint pushes are separate GitHub processing issues.
Automatic CI, recovery execution and new hosted-AI generation are not enabled by
this stage. Existing [deployment limits](next-session.md#explicit-remaining-limits)
remain explicit.
