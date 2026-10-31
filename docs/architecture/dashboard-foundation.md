# Dashboard foundation

## Status

The owner approved the graph-first light design with expanded execution attempts. The initial Stage 8 dashboard is implemented in `apps/pipeguard/web/`: overview, execution/attempt selection, incident history and a read-only API connection. The initial React Flow graph from Stage 9 is included. Preview fixtures remain explicitly separate from live data. See [verification](../dashboard-verification.md) for browser and automated checks.

## Graph technology decision

Retain PostgreSQL as the lineage system of record. Use React Flow (`@xyflow/react`) for the interactive two-dimensional lineage view. Do not introduce Neo4j or Three.js for the initial dashboard.

The implemented lineage API already serves job-scoped historical traversal with execution/time filters, evidence references and explicit completeness limits. It returns at most 200 nodes and 1,000 links, using at most 1,000 source events. The display must preserve dataset → step execution → dataset relationships and the API's observed-union semantics.

Neo4j is a graph database, whereas React Flow is a React diagram component and Three.js is a 3D rendering library. These solve different problems. A second database would require migration, synchronization, authorization and provenance consistency across stores. Current requirements do not establish a need for that additional boundary. A two-dimensional diagram also keeps node labels, selection and a textual alternative straightforward to inspect.

Reconsider storage only if representative measurements show bounded PostgreSQL traversal cannot meet agreed latency or scale requirements. Reconsider 3D only for a specific user task with an accessible equivalent and measured usability benefit. This decision does not claim unmeasured performance or that 3D is inherently unusable.

## Initial screen scope

- Application shell and pipeline overview with actual monitoring mode and freshness.
- Execution history with distinct run and attempt states. A successful retry preserves the earlier failed attempt and its reason.
- Incident queue and evidence detail with source identity, source time, receipt time and missing-evidence indicators.
- An interactive graph view that retains execution scope, partial/truncated status and source references when selecting nodes or links.

Do not infer business health from execution success or detector freshness. Quality, lineage completeness, execution outcome and monitoring coverage are separate signals. Do not imply that raw logs, AI investigation, recovery execution or unsupported detectors are available.

## Implementation boundaries

The web application belongs inside `apps/pipeguard/`; sample workloads remain separate. Use the agreed Node.js 22 and pnpm environment and commit its lockfile when packages are introduced. Verify current framework compatibility before installation.

Keep API credentials exclusively on the server. Do not expose an admin token through browser bundles, public environment variables, URLs or browser storage. The existing API rejects Origin-bearing requests; do not weaken that boundary without reviewing the dashboard authentication and request flow. The implemented broker uses a fixed loopback destination, explicit GET-only path allowlist, validated identifiers, upstream timeout, no-store responses, exact local Host/Origin checks and Fetch Metadata rejection. It uses the existing owner credential server-side; browser access does not provide multi-user identity. The launcher excludes unrelated service credentials.

## Stage 8 acceptance

Review desktop and mobile layouts, keyboard navigation and visible focus. Verify loading, empty, unavailable, unauthorized, stale and partial-data states. Preserve incident and attempt history across selection and refresh. Use text as well as color for states. Clearly distinguish demonstration data from live data and show the time of the latest successful refresh. Record actual checks separately from planned behavior.

## Official references

- [React Flow](https://reactflow.dev/): interactive React node diagrams.
- [Neo4j graph database](https://neo4j.com/docs/getting-started/graph-database/): node and relationship storage.
- [Three.js fundamentals](https://threejs.org/manual/pages/fundamentals.html): browser 3D rendering.

References reviewed on 2026-10-31. Next.js, React Flow and Phosphor packages are now pinned in the frontend pnpm lockfile. No additional database, 3D renderer or cloud service was introduced.

- [Next.js installation](https://nextjs.org/docs/app/getting-started/installation)
- [Next.js backend for frontend](https://nextjs.org/docs/app/guides/backend-for-frontend)
- [React Flow accessibility](https://reactflow.dev/learn/advanced-use/accessibility)
- [Phosphor React icons](https://github.com/phosphor-icons/react)
