# PipeGuard dashboard

The local monitoring UI uses Next.js 16, React 19, TypeScript, React Flow and ECharts. It belongs to the monitoring application and reads stored monitoring evidence. Its separate executable recovery controls can request one approved sample run through a supervised worker; that run may change the sample warehouse. The browser has no direct warehouse access or Airflow credentials.

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

See [dashboard verification](../../../docs/dashboard-verification.md) and the root design QA report for the actual checks and remaining boundaries. See [exploration verification](../../../docs/exploration-verification.md) for charts, timeline and measured graph fixtures. Selected incidents offer advisory AI investigation, review-only recovery and separate executable recovery controls. Public hosting is not implemented.

## Hardening follow-up

Production scripts use a fresh per-document nonce and dynamic rendering, including error pages. Inline positioning styles remain necessary for React Flow/ECharts. Lists use bounded five-minute captured snapshots; capture times are visible, Refresh resets pagination, and expiry/capacity errors never silently switch to live pages. Quality conflict summaries cover the complete selected scope. Dense graph text views support search, type filters and keyboard selection while preserving graph data.

Overview includes independent watcher status with a 15-second refresh, separate from manual metadata refresh. See [resilience operations](../../../docs/local-resilience.md) and [hardening verification](../../../docs/hardening-verification.md).

## Advisory investigation

Incidents now offer explicit manual generation through a fixed same-origin broker. Groq credentials stay on the API server. Requests and outcomes are durable; uncertain submissions retain their request key for replay. Qualified summaries are shown by default; generated prose and exact evidence projections are separately expandable. Preview mode never submits records. See [operations](../../../docs/investigation-operations.md) and [verification](../../../docs/investigation-verification.md).

## Recovery review

Select **Incidents → an incident → Recovery review**. This section precedes investigation history so it remains reachable as retained AI history grows. The server admits proposals only for the explicitly configured sample job and eligible current failure evidence. Preview never submits review operations. The current paused DAG and resolved incidents remain blocked.

Creating a proposal does not start a run. Review approval or rejection requires checking the exact-proposal confirmation; both decisions are immutable. The proposal/hash inspector shows the exact impact, parameters and expiry. Unknown responses retain the original body/key for explicit replay. These are review-only decisions and cannot authorize current or future execution. See [operations](../../../docs/recovery-operations.md) and [verification](../../../docs/recovery-verification.md).

## Executable recovery

The separate **Executable recovery** section requires an eligible incident, fresh monitoring evidence and both operator-controlled execution switches. It uses a fixed same-origin route and a supervised worker with its own restricted credentials. Approval of the exact proposal and starting its run are separate confirmations. Proposals expire after five minutes; review-only approvals cannot authorize execution.

Saved uncertain requests retain their exact body and key for explicit replay. A replay cannot dispatch a second start for an existing intent. Refresh history or check the external run outcome to inspect uncertainty; neither operation assumes that a lost response means no run started. Earlier failures and successive dispatch observations remain retained. History is paged five proposals at a time.

Execution is normally disabled and the sample DAG paused. Preview submits no recovery commands. See [execution operations](../../../docs/recovery-execution.md), [dashboard verification](../../../docs/recovery-dashboard-verification.md) and [controlled live verification](../../../docs/recovery-live-verification.md).
