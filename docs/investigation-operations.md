# Advisory investigation operations

Stage 10's **initial local advisory slice is verified**. Manual investigation is available through the incident dashboard, authenticated API and CLI. Requests and outcomes are retained in PostgreSQL. This is a bounded advisory implementation; the fixed bounded evaluation gate passes, while broader live incident-class coverage remains limited. AI cannot change deterministic incident state or execute recovery.

## Configuration and free-tier boundary

The operator selected Groq and confirmed the organization is on its **Free plan**. Private root `.env` settings are:

```dotenv
GROQ_API_KEY=your_private_key
PIPEGUARD_INVESTIGATION_ENABLED=true
```

The enable flag defaults to false in the example file. Restart the API after changing these values. The dashboard receives only its API credential; the Groq key never reaches browser code. The account's billing plan cannot be verified through the model-list endpoint. Keep the organization on Free: an operator confirmation or an application request limit cannot prevent charges after a paid-plan upgrade. No automatic model fallback, billing upgrade or retry exists.

The configured model is `openai/gpt-oss-120b`, hosted by Groq, with low reasoning effort and policy `investigation_v10`. It replaces the preview Qwen model after the fixed evaluation exposed insufficient usefulness and a provider JSON-generation failure. Authenticated availability was verified on 2026-11-02. Availability and model status do not prove incident accuracy. See the [evaluation protocol and results](investigation-evaluation.md). No new Python or web dependency was required, and no OpenAI API credential is used.

## Dashboard and API

Select **Incidents → an incident → AI investigation**. Confirm the selected evidence may go to Groq and that the organization remains on Free, then choose **Investigate incident**. Preview mode never submits demonstration records. Refreshing history is a local read and does not generate another response.

- `POST /v1/incidents/{incident_id}/investigations`: administrator-only. Body: `request_key` UUID, literal boolean `free_plan_confirmed: true`, optional `bundle_id` UUID. Without a bundle ID, capture a fresh bounded bundle for this incident. The API accepts no custom prompt or model parameter.
- `GET /v1/incidents/{incident_id}/investigations`: authenticated, scoped to the producer's integration or administrator. Up to 20 records per page, newest first. Follow `next_before` as `before` to read older records; retained history is not truncated. This is a live keyset view, not a frozen response snapshot.
- The dashboard broker uses fixed local endpoints, strict Host/Origin/Fetch Metadata checks for submission, JSON-only bounded bodies and bounded upstream responses. It never forwards browser-selected destinations or provider credentials.

This remains a trusted local-machine interface. Loopback and browser-origin checks are not authentication between different local operating-system users or hostile local programs. Public or multi-user deployment requires a separate authorization design.

## Durable state and interruption behavior

Migration `e7c2b936a410` adds `investigation_requests` and `investigation_outcomes`. Both reject row changes, deletion and truncation through immutable-history triggers; the runtime role has SELECT/INSERT only. Database owners can still alter protections. Each request references an immutable evidence bundle and stores the outbound projection, citation mapping, input hash, model, prompt version and actor. Current requests also retain the exact system prompt, response schema and inference settings. No secret headers are stored.

The request commits **before** contacting Groq. A terminal result or failure is appended separately, with safe validation diagnostics where available. A request without a terminal outcome is `pending` for two minutes, then `unknown`; clock-inconsistent future records are also unknown. Unknown does not mean Groq did no work. Reusing the same request key returns its recorded state without another generation, including across API restarts and failures. Reusing a key for a different incident/bundle is rejected.

The dashboard retains an unconfirmed submission key during network/database uncertainty. It offers explicit replay of that same key. It does not forget the key merely because a database error was returned after generation. There is no background retry or automatic recovery. A deliberate new request creates another record; previous failures remain visible.

Application admission uses a PostgreSQL session lock, a recent-unsettled-request guard, one minute between new requests and a limit of **20 requests per rolling 24 hours** across the API's database. These are conservative application limits, not organization-wide Groq accounting. Requests rejected during projection still count. Provider calls and database writes cannot be one atomic transaction; a lost terminal write remains unknown and manual new submissions can repeat similar work.

## Evidence and grounding boundaries

The outbound projection is capped at 6,000 bytes. It contains only machine states, enumerated error codes, attempt numbers, normalized execution/report times, quality counts and completeness/reconciliation flags. Run identifiers become temporary aliases. Dataset/rule names, external identifiers, database UUIDs, SQL, logs, credentials and arbitrary source prose are excluded. Integrity mismatches, truncated bundles and oversized/invalid projections fail before provider inference; older failures are not silently trimmed.

Current decoding is constrained to finding categories and primary citations supported by this packet. A finding has one primary supporting citation and at most one incompatible same-run/same-attempt terminal-state counter-citation. If such contradictory evidence exists for the chosen primary citation, omitting it is rejected. Later successful attempts are recovery context, not contradictions of earlier failures. Lineage gaps cannot be offered as execution-failure causes. Unsupported categories, duplicate/overlapping/unknown citations and inconsistent abstention are rejected locally. With no supported category, the local gate abstains without a provider call; the outcome records that distinction.

The UI displays fixed, qualified summaries such as **producer-reported source failure; underlying cause unverified**. Generated explanatory prose is explicitly unverified and collapsed. Next checks come from a small enumerated set of human inspection tasks, not executable commands. Responses from earlier prompt policies remain in audit history and are not endorsed by the current rules. A real response exposed spurious alternatives during this checkpoint; the response was retained, the issue was addressed by category/citation constraints, and subsequent rejected responses were retained as separate failures.

These checks do **not** prove arbitrary generated prose correct, calibrate confidence, establish business impact or identify an unseen root cause. Quality counts omit rule identity and cannot establish cross-report rule conflicts. Missing evidence can require abstention. Rejected raw provider bodies are withheld; fixed error codes and bounded, input-free validation diagnostics are retained instead.

## Network and response limits

Each accepted submission attempts at most one Groq generation. The configured completion cap is 4,096 tokens including reasoning, and the provider response cap is 256 KiB. A 45-second elapsed budget is checked between reads with 10-second socket timeouts; this is not a hard process-level deadline for OS/DNS operations. Redirects, proxy inheritance, tools, streaming and automatic retries are disabled. Validated output has an additional 12,000-byte limit; durable input is bounded before insertion. A rate-limit error is recorded and does not change incident state. Local API cooldown/budget errors retain their local codes in CLI diagnostics rather than being mislabeled as provider quota exhaustion.

## CLI

```sh
# Local projection only; no Groq request.
uv run --locked --env-file .env python scripts/investigate.py --bundle-id BUNDLE_UUID --dry-run

# Durable API-backed submission of exactly this stored bundle.
uv run --locked --env-file .env python scripts/investigate.py --bundle-id BUNDLE_UUID --free-plan-confirmed

# Replay an existing request; never regenerate its recorded operation.
uv run --locked --env-file .env python scripts/investigate.py --bundle-id BUNDLE_UUID --request-key REQUEST_UUID --free-plan-confirmed

# Explicit synthetic connectivity probe; outside the incident ledger/admission budget.
uv run --locked --env-file .env python scripts/investigate.py --verify-connection --free-plan-confirmed
```

The connectivity probe sends synthetic data and saves a private local file under ignored `data/local/investigations/`. It is a diagnostic exception, not the normal incident workflow. Initial prototype files predate durable API records and are not retroactively imported.

See [verification](investigation-verification.md) and [evaluation](investigation-evaluation.md) for measured checks and remaining acceptance work, and [Stage 11 design](recovery-design.md) for the recovery boundary. Official references: [Groq structured outputs](https://console.groq.com/docs/structured-outputs), [model status](https://console.groq.com/docs/model/openai/gpt-oss-120b), [rate limits](https://console.groq.com/docs/rate-limits), [data handling](https://console.groq.com/docs/your-data), [billing](https://console.groq.com/docs/billing-faqs), [PostgreSQL advisory locks](https://www.postgresql.org/docs/17/explicit-locking.html#ADVISORY-LOCKS).
