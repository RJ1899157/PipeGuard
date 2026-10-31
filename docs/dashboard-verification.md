# Dashboard verification

## Scope

Initial local dashboard checkpoint, 2026-10-31. The owner approved the light graph-first layout with expanded execution attempts. This checkpoint introduces the web runtime and read-only metadata broker; it does not change database migrations, incident rules, workload execution or recovery privileges.

## Automated checks

| Check | Result |
| --- | --- |
| Existing monitoring/PostgreSQL suite | 188 passed; one upstream Starlette/httpx deprecation warning |
| Independent orders workload suite | 45 passed |
| Web boundary, graph layout and preview consistency tests | 10 passed |
| TypeScript / production build | Passed using Node.js 22.20.0 |
| Alembic metadata comparison | No new upgrade operations detected |
| Production dependency advisory query | No known advisories reported by pnpm at this checkpoint; not a complete security audit |
| Browser asset scan | Administrator token absent from all 13 emitted static assets |
| Whitespace/diff check | Passed |

The ten web tests cover exact local Host/Origin/Fetch Metadata checks, fixed read-path routing, invalid identifier and pagination bounds, encoded run identity, branching/cyclic/disconnected/200-node graph layout, independent retry fixtures, provenance timestamps and preview error states. The 200-node check is a deterministic layout check, not a browser performance benchmark.

## Running HTTP boundary checks

The production dashboard returned:

- 200 for allowlisted monitoring coverage.
- 403 for an unknown Host, cross-site Origin and cross-site Fetch Metadata.
- 405 for POST to its read broker.
- 400 for unsupported resources and invalid/path-traversal identifiers.

HTML includes no-store, frame denial and content-type protection. The upstream API retains its existing Origin rejection. The browser never sends the administrator bearer credential. The launcher now invokes the Next.js entry point with the explicitly verified Node.js 22 executable; it does not depend on the package manager wrapper's internal runtime.

## Browser checks

Production build inspected in the in-app browser at 1440 × 1024, 768 × 1024 and 390 × 844 CSS pixels. No horizontal page overflow was observed. The final tested views produced no browser console warnings/errors. A live page left unrefreshed was observed to change its cached monitor status to unknown with a refresh-needed notice after the freshness window.

Live reads verified the orders job's latest stored retry: overall run succeeded; first attempt failed with `source_unavailable`; second attempt succeeded. The normal root URL uses those stored records. The preview URL is explicitly labelled demonstration data and uses independent fixtures.

Checked navigation, run/attempt selection, graph selection/zoom/fit, keyboard Enter/Tab and visible focus, selected-node evidence, source/receipt timestamps, original lineage record display, incident transitions, empty page-local filtering and manual refresh. Empty/unavailable/unauthorized/stale displays were additionally checked using preview fixtures; they do not constitute actual outage or credential-expiration experiments.

The visual review found and corrected stale incident selection after filtering, missing keyboard-to-inspector updates, resize fitting and attempt-detail density. See [design QA](../design-qa.md) for comparison history and accepted content differences.

## Review artifacts

All checked-in screenshots below use synthetic preview data, never credentials or workload rows.

- [Approved visual concept](design/dashboard-reference.png): contains conceptual fields and mixed-scope warnings that are intentionally corrected in implementation.
- [Implemented desktop](design/dashboard-desktop.jpg)
- [Expanded attempts](design/dashboard-attempts.jpg)
- [Implemented mobile](design/dashboard-mobile.jpg)

## Remaining boundaries

This is a local owner interface with read-only routes, not multi-user authentication or a public deployment. Quality enrollment is displayed without claiming the checks passed. Incident history and metadata are paged; filtering applies to the current incident page. Evidence references are bounded and additional retained references are explicitly labelled. Source assertions and hashes do not establish independent root cause.

Stage 9 still needs quality charts, timeline expansion and measured rendered-graph workloads. AI investigation, approved recovery execution, CI and the final integrated security/performance review remain later stages. No claim of production readiness or exhaustive failure coverage is made by this UI checkpoint.
