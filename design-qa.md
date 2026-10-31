# Dashboard design QA

**final result: passed**

## Comparison target

- Source visual truth: `docs/design/dashboard-reference.png` (approved combined graph-first concept; synthetic data).
- Implementation: `docs/design/dashboard-desktop.jpg`, captured from the production build at `/?preview=1&capture=final`.
- Source: 1487 × 1058 pixels; generated concept with no browser CSS density.
- Implementation: 1440 × 1024 pixels, 1440 × 1024 CSS viewport. Comparison uses the nearly identical frame aspect ratios and proportional layout; no claim of pixel-identical density or content.
- State: light theme, orders retry example, successful second attempt selected, staging dataset inspector. Both attempts remain visible.
- Full-view comparison: source and final desktop capture were opened together in the same comparison input.
- Focused comparison: `docs/design/dashboard-attempts.jpg` (1026 × 394 capture) was opened with the source and desktop capture to review failure reason, projection source, timestamps, and retained second attempt.
- Responsive evidence: `docs/design/dashboard-mobile.jpg` (390 CSS pixels wide, full page); 768 × 1024 tablet layout inspected separately.

The design reference is a concept, not a source of product facts. Its mixed-attempt warning, dataset availability claims, invented layer/description fields and task-log labels are intentionally not implemented. The product displays only fields supplied by the API. The selected graph's completeness is independent of earlier attempts.

## Findings and comparison history

1. **P2 — graph fit and density.** The initial narrow-window render retained its zoom after resizing; labels were too small in the desktop composition. Reduced node spacing/width and added container-resize fitting. Reopened the production build at desktop/tablet/mobile sizes. The final graph retains all nine example nodes, zoom controls and a text node/link alternative. Long canonical names wrap rather than being replaced with invented labels.
2. **P2 — attempt hierarchy and readability.** Initial preview banners and spacing pushed attempt outcomes too far down. Removed duplicate desktop preview text while retaining the visible header label, tightened graph spacing and increased primary failure-detail text to 13px on desktop / 12px on mobile. The final desktop capture shows both attempt outcomes; the full page retains their detail and evidence action.
3. **P2 — keyboard selection drift.** Initial keyboard graph selection did not update the controlled inspector. Handle selection changes through `onNodesChange`. Retested Enter on `raw.orders`: focused node, selected node and inspector all agree. Tab advances to the next node with visible focus.
4. **P2 — filtered incident selection.** Initially, filtering a resolved incident out of the queue left it in the inspector. Clear selected incident/history page when changing the filter. Retested: the empty open-only queue now shows an unselected history panel.

Post-fix production screenshots are the implementation evidence above. Earlier intermediate captures are retained only in ignored local `work/dashboard-qa/`; they are not the final product screenshots.

## Required fidelity surfaces

| Surface | Review |
| --- | --- |
| Fonts / typography | Local Arial/Helvetica sans-serif matches the concept's neutral typography direction; no remote font requests. Clear heading hierarchy, readable primary failure explanations, smaller timestamps/identifiers. Long identifiers wrap or use native selector truncation. |
| Spacing / layout rhythm | Light top navigation, graph left, evidence right, expanded attempts below graph. Additional live pipeline/run/attempt selectors intentionally add vertical space. Smaller screens stack sections without page overflow. |
| Colors / tokens | Violet selection/action, muted blue metadata, distinct red/green attempt surfaces and amber unknown/partial signals. Text and icons accompany state colors. |
| Image / asset fidelity | Phosphor library icons; React Flow renders the actual interactive graph. No raster screenshot substitutes for controls, CSS illustrations or fabricated logos. Captures are browser-generated JPEGs, not generated implementations. |
| Copy / content | Live and demonstration modes clearly distinguished. No successful retry erases a failure; no freshness/quality/lineage signal is inferred solely from execution success. Source/receipt times are separate. Unsupported fields from the concept are omitted. |

## Interaction and state checks

- Live API records: both jobs available; latest orders run succeeds with failed first attempt and successful second attempt retained.
- Demo attempt selection: first-attempt partial graph and second-attempt reported-complete graph remain separate.
- Node click, keyboard Enter/Tab, inspector, source record expansion, graph fit, text alternative, navigation and manual refresh checked.
- Incident selection/history and empty page-local filter checked.
- Loading observed during real connection; empty, stale, unavailable and unauthorized states also inspected using explicitly labelled preview fixtures. These fixtures do not prove a real service outage or expired credential.
- No horizontal page overflow at 390, 768 or 1440 CSS pixels.
- Production browser console inspected: no warnings or errors in the final checked views.

## Open questions

None blocking the initial dashboard foundation. The existing local owner boundary does not provide multi-user identity or permission management.

## Implementation checklist

- [x] Approved composition implemented with live data and separately labelled preview fixtures.
- [x] Failure and retry preserved, graph scoped per attempt.
- [x] Keyboard inspector consistency and filter reset corrected and retested.
- [x] Desktop/mobile, empty/loading/error and stale/partial states inspected.
- [x] Automated checks, production build and credential/boundary checks recorded separately.

## Follow-up polish

- P3: long fully qualified graph labels can wrap over several lines; retain canonical identity in the inspector if adding shorter display labels.
- P3: the additional real selection controls require some vertical scrolling to reach all evidence actions. They remain keyboard reachable and do not overlap or clip.
- Representative browser graph performance, quality charts and execution timeline expansion remain Stage 9 work.


## Stage 9 audit follow-up — 2026-10-31

The rebuilt production UI was inspected in the in-app browser at 1440, 768 and 390 pixels. Timeline selection, quality report conflicts, graph keyboard selection/clear, exact dependency evidence, incident history boundary pagination and all four navigation views were exercised. Fixed cycle layout, stable selected-link identity, Escape re-selection and accidental timeline spacer hatching. See [exploration verification](docs/exploration-verification.md) and [system audit](docs/system-audit.md) for current evidence and limits. Earlier screenshots above describe the foundation checkpoint, not these new checks.
