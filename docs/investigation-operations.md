# Advisory investigation: first integration checkpoint

Stage 10 is **in progress**. This checkpoint implements manual CLI investigation of an existing immutable evidence bundle. It does not add dashboard controls, persisted investigation database records, an API route or recovery execution.

## Provider and cost boundary

The operator selected Groq and confirmed the account is on its Free plan. The private root `.env` contains `GROQ_API_KEY`; the key is never passed to the browser or printed. Model-list authentication succeeded on 2026-11-02. The model-list API does not expose or verify the account's billing plan.

The initial integration uses `qwen/qwen3.8-27b`, available to the account and documented as supporting strict JSON Schema output. Groq labels it a **preview model**: availability may change. Its use here verifies the integration, not a final production model selection or proven investigation quality. No automatic model fallback or paid-plan upgrade exists. Every generation requires the operator's `--free-plan-confirmed` assertion; this flag cannot technically verify billing or prevent charges if the operator subsequently upgrades the account. Keep the account on Free.

Each invocation makes at most one generation request, with a 6,000-byte projected evidence cap, 2,048 maximum completion tokens, a 256 KiB response cap and a 30-second socket timeout. There is no automatic retry, tool use, streaming, proxy inheritance or redirect following. A quota error returns `provider_rate_limited`; wait before deliberately retrying. Limits are account/model-specific. This is not an absolute wall-clock deadline or a global cross-process request budget.

## Manual operation

From the project root, with the existing API running:

```sh
# Inspect a stored bundle locally; no Groq request.
uv run --locked --env-file .env python scripts/investigate.py --bundle-id BUNDLE_UUID --dry-run

# Synthetic provider connectivity and response validation; no live incident evidence.
uv run --locked --env-file .env python scripts/investigate.py --verify-connection --free-plan-confirmed

# Explicitly submit the bounded projection of this selected stored bundle.
uv run --locked --env-file .env python scripts/investigate.py --bundle-id BUNDLE_UUID --free-plan-confirmed
```

The bundle must already exist; this command does not capture additional evidence or query a workload. It reads a selected bundle through the fixed local authenticated API. Integrity mismatches, truncated bundles, missing attempt/run bindings, oversized projections and unusable evidence fail closed before generation. There is no silent trimming of older failed attempts to fit the provider budget.

## Evidence and response boundary

Only an allowlisted projection leaves the machine: execution states, enumerated error codes, attempt numbers, normalized execution/report times, quality status counts, completeness/reconciliation flags and a known incident condition. Run identifiers become temporary aliases. Dataset names, rule names, external identifiers, SQL, logs, credentials, arbitrary free text and original database UUIDs are excluded. Some bundle fields are deliberately not sent. Quality counts do not preserve rule identity and cannot establish cross-report rule conflicts.

The response has at most three ranked hypotheses, supporting/contradicting citation IDs, low/medium confidence, advisory next checks or an explicit abstention. Local validation rejects unknown citation IDs, duplicate/overlapping citations, inconsistent abstention and malformed or oversized output. The instructions require preserving failed attempts after successful retries and treating source claims as untrusted. No response can change deterministic incident state or execute recovery.

Citation membership and schema validation **do not prove factual correctness**, causal attribution or prompt-injection resistance. Generated text remains untrusted. Repeatable groundedness, contradiction, missing-evidence, injection and provider-failure evaluations, durable investigation audit records, API authorization and dashboard presentation remain required before Stage 10 is complete.

## Private records and verification

Accepted results are written atomically as owner-private, randomly named JSON files in ignored `data/local/investigations/`. Each includes provider/model/prompt version, the exact outbound projection and its hash, local source-reference mapping, bundle hash, response and timestamp. These files are not immutable database audit records, do not preserve the full source bundle, and do not establish reproducibility of model output. The original immutable bundle remains in PostgreSQL. Console output contains only status and the local record path; raw provider failures are withheld.

On 2026-11-02, a synthetic failed-attempt/successful-retry example returned a schema-valid, citation-checked abstention. A local-only projection of the existing stored bundle retained 14 evidence items in 1,934 bytes; no live incident evidence was sent during verification. The first generation attempt was rejected with HTTP 403; an explicit application User-Agent resolved the transport rejection. No broad regression suite was run for this new checkpoint.

Official references: [Groq structured outputs](https://console.groq.com/docs/structured-outputs), [Qwen model status](https://console.groq.com/docs/model/qwen/qwen3.8-27b), [rate limits](https://console.groq.com/docs/rate-limits), [data handling](https://console.groq.com/docs/your-data), [billing](https://console.groq.com/docs/billing-faqs).
