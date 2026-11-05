# Stage 14 final project audit

Started 2026-11-04; resumed 2026-11-05 after an interrupted session.
Status: **fixes implemented; final acceptance in progress**.
Baseline: `ce4361c4c6a1b4f14237af6f5703ccc2fe6e69a7`.

## Scope and method

Three independent reviewers covered backend/persistence/contracts, dashboard and
operational/workload/recovery code. The coordinator reviewed their changes,
checked the running browser, measured graph geometry and coordinated fresh-export
acceptance, restores, immutable-row checks, dependency checks and Git attribution.
Generated contracts and lockfiles receive structural/provenance/runtime-equality
checks; this is not a manual audit of third-party dependency implementations.

## Confirmed fixes

| Finding | Correction | Verification |
| --- | --- | --- |
| Ambiguous colon-prefix evidence scope and run named `job` | Derive scope from incident condition and match exact run identity; preserve historical bundles | Seven unique-schema regressions; independent cross-review of every detector condition |
| Backward/frozen wall clock could extend cached freshness | Require valid, nonnegative wall and monotonic ages, both at most 90 seconds | Three deterministic regressions; no OS-clock change claimed |
| Long valid graph names overlap adjacent nodes | Bound visual labels to three lines, retaining full accessible/detail names | Before: 200-node fixture has four overlap pairs, maximum height 383 px; after measurement pending |
| Low small-text contrast | Darker footer and attribution text | Token contrast regression; rendered computed-colour check pending |
| UTC conversion overflow misclassified malformed source data | Catch overflow as `InvalidSource` | Upper/lower timestamp-boundary regressions |
| Connectivity diagnostic generated outside normal incident admission | Fixed authenticated model-metadata GET only; remove direct generation path | 18 mocked CLI/allowlist cases; no live provider request |
| Current operating docs described already implemented features as pending | Update runtime, recovery namespaces and current-versus-historical verification wording | Documentation and link checks |

The baseline fresh-export run passed 566 cases plus HTTP/contract/build checks;
that result predates these fixes. Final results will identify their own committed
revision. Three fresh database backups passed disposable restores before the
interruption. No hosted AI generation, recovery action or retained business run
is authorized as an audit shortcut.

## Boundaries retained

Recovery stays disabled and the sample DAG stays paused. The immutable baseline
contains 8,226 rows across 15 tables; later background observations may append.
Independent off-device monitoring/backups are declined for this local project.
The old stuck GitHub run is deferred. Container advisory and broader deployment,
AI-accuracy and atomic-publication limits remain explicit; this audit cannot
establish universal optimality, zero vulnerabilities or exhaustive permutations.
