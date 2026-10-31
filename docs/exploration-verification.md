# Graph and chart exploration verification

## Checkpoint scope

Stage 9 adds an execution-attempt timeline and selected-report quality charts to the approved dashboard layout. Deterministic incident state and recovery permissions are unchanged. The additive quality-history API preserves every report; source timestamps and receipt timestamps remain separate.

## Measurement plan

Use the production Next.js build in the in-app browser on the development laptop at 1440 × 1024 CSS pixels. Measure three page loads each for a 200-node/1,000-link branching graph and a 200-node/200-link cyclic graph, with a **2,000 ms graph-ready budget** per sample. The graph-ready attribute measures from the graph component's render start until all graph nodes have nonzero measured dimensions and the next animation frame runs. This is a DOM-readiness measure, not network startup, first contentful paint, frame rate or a production SLA.

Fixtures are available only through explicitly labelled preview data: `/?preview=1&graph=stress` and `/?preview=1&graph=cycle`. Their lack of real provenance is visible as partial synthetic evidence. Live graph data is never replaced by these fixtures without preview mode. Verify node/link counts, keyboard/text selection and inspector consistency separately; a fast render alone does not establish usability.

## Results

Verified on 2026-10-31 with the production build, Node.js 22 and the in-app browser at 1440 × 1024.

| Fixture | Nodes / links retained | Graph-ready samples (ms) | Budget |
| --- | --- | --- | --- |
| Branching | 200 / 1,000 | 493.9, 420.9, 445.4 | All below 2,000 ms |
| Cyclic | 200 / 200 | 362.9, 367.8, 358.7 | All below 2,000 ms |

The layout condenses strongly connected components before arranging the graph. The cycle now fits the overview instead of producing a roughly 28,000-pixel vertical chain. Fit view, zoom, keyboard nodes and links, textual dependency selection, and exact-link provenance were checked. At 200 nodes, overview labels are necessarily small; zoom and the textual alternative remain required for detailed inspection. These are bounded fixture results, not maximum supported throughput or frame-rate measurements.

## Interaction and data checks

- Timeline duration-bar click selects the matching attempt; expanded cards provide the keyboard alternative. Failed attempt 1 remains visible after successful attempt 2. Unfinished/invalid intervals are omitted with notice. Waiting offsets are invisible, including under ARIA decals; only actual durations are patterned.
- Quality reports preserve all five statuses and missing failure counts. Selecting an older passing report does not hide conflicts in the loaded reports. Counts are per selected report; partial inventories remain explicit. No report is unknown, never inferred passing.
- Graph node Enter selects its detail; focused dependency Enter selects exact-link evidence. Escape clears focused graph selection. Background clear, text links, zoom in/out and fit view are connected. Source record expansion retains source/receipt timestamps and hashes.
- Incident state filtering, history expansion and exact-50 history pagination were checked. An empty second page keeps Previous available and returns to all 50 first-page records.
- Overview, Pipelines, Incidents and Lineage navigation, Inspect, Refresh, preview/live links, job/run/attempt selectors and evidence open/close were checked. Inactive views no longer request unrelated metadata.
- Empty, unavailable, unauthorized and stale preview states display explicit uncertainty. Live API records show the existing successful retry with the earlier failure and a 14-check quality report.
- Desktop 1440, tablet 768 and mobile 390 pixel layouts were inspected; no page-level horizontal overflow at tested widths. Mobile evidence remains reachable. No browser errors/warnings were captured in the checked session.

## Automated verification

21 frontend tests, strict TypeScript unused checks, formatting and the production build passed. Backend contract checks validate the checked-in OpenAPI and event schemas against runtime models. The complete cross-system results and limitations are in [system audit](system-audit.md).

Fresh synthetic screenshots are retained in [audit screenshots](audit/). This is targeted keyboard/responsive verification, not a formal accessibility certification. Offset pagination remains susceptible to concurrent insert movement; conflict notices cover loaded reports, not reports on unvisited pages.
