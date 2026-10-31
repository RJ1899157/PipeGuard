# PipeGuard dashboard

The local monitoring UI uses Next.js 16, React 19, TypeScript, React Flow and ECharts. It belongs to the monitoring application; it does not execute sample workloads or access their warehouse.

## Start

Use Node.js 22 and pnpm 11.25.0. From the repository root:

```sh
pnpm --dir apps/pipeguard/web install --frozen-lockfile
pnpm --dir apps/pipeguard/web build
uv run --env-file .env python scripts/run_dashboard.py
```

The provisioned API must already be running on `127.0.0.1:8000`. Open `http://127.0.0.1:3000`. The launcher verifies Node.js 22, binds the dashboard to loopback, disables Next.js telemetry and passes only the API credential plus basic process environment to the web server. Database and Airflow credentials are excluded. Ctrl+C stops the dashboard. Use `--dev` for development instead of the production build.

Before rebuilding production assets, stop the running dashboard. After the build completes, start the launcher again and reload open dashboard tabs. Replacing `.next` under a running production server can leave old HTML referring to missing chunks.

The dashboard is a **local owner interface**, not a multi-user authentication service. Any process running as the local owner can access it. Do not expose it through a public tunnel, reverse proxy or network interface. Remote deployment and user-specific authorization require their own reviewed design.

## Available views

- **Overview:** pipeline catalog, monitoring mode and detector status. Instrumentation coverage is not business health.
- **Pipelines / Lineage:** execution selection, attempt-scoped interactive graph, textual node/link alternative, expanded attempt history with reported failure reason, projection source and timestamps, an execution timeline and selected-report quality charts.
- **Incidents:** paged queue, page-local state filtering, and immutable transition history.
- **Evidence:** selected-node or selected-dependency lineage source references, source/receipt times, payload hashes and the original stored lineage record. This is not a raw-log viewer or AI root-cause determination.

The browser reads only an allowlisted set of metadata routes through `/api/read`. Upstream URLs and HTTP methods are fixed server-side. Host, Origin and Fetch Metadata checks reject cross-site metadata requests and DNS rebinding hosts. A top-level navigation to the local app shell may originate elsewhere; iframe, cross-origin fetch and metadata exceptions are not allowed. The existing API's Origin rejection remains unchanged. Credentials stay in a `server-only` route handler and are not returned to the browser. Metadata responses use `no-store`; refresh is manual, displayed explicitly. Once the coverage fetch is over 90 seconds old, the UI stops presenting its cached freshness as current.

The initial quality indicator reports whether quality evidence is expected; it does not claim check results passed. Graph completeness applies only to the selected execution attempt and the producer-declared inventory. Earlier failed attempts and partial lineage remain inspectable.

## Preview and verification

`/?preview=1` selects clearly labelled demonstration records and makes no dashboard API reads. The normal root URL uses stored live data. Preview records are product fixtures, not personal learning materials.

For reproducible UI-state inspection, preview mode also accepts `state=empty`, `state=stale`, `state=unavailable`, `state=history50`, or `state=unauthorized`. These simulate display states only; they do not change the API, incident state, stored evidence or credentials. Without `preview=1`, the state parameter has no effect.

```sh
pnpm --dir apps/pipeguard/web typecheck
pnpm --dir apps/pipeguard/web test
pnpm --dir apps/pipeguard/web build
pnpm --dir apps/pipeguard/web exec prettier --check app components lib tests proxy.ts next.config.ts
```

See [dashboard verification](../../../docs/dashboard-verification.md) and the root design QA report for the actual checks and remaining boundaries. See [exploration verification](../../../docs/exploration-verification.md) for charts, timeline and measured graph fixtures. AI investigation, recovery controls and public hosting are not implemented.

## Hardening follow-up

Production scripts use a fresh per-document nonce and dynamic rendering, including error pages. Inline positioning styles remain necessary for React Flow/ECharts. Lists use bounded five-minute captured snapshots; capture times are visible, Refresh resets pagination, and expiry/capacity errors never silently switch to live pages. Quality conflict summaries cover the complete selected scope. Dense graph text views support search, type filters and keyboard selection while preserving graph data.

Overview includes independent watcher status with a 15-second refresh, separate from manual metadata refresh. See [resilience operations](../../../docs/local-resilience.md) and [hardening verification](../../../docs/hardening-verification.md).
