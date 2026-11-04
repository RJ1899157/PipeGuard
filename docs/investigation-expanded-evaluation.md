# Expanded advisory investigation evaluation

Protocol frozen **2026-11-04**, before live trials. Status: **version-11 expanded gate passed; earlier failed cohorts retained**.
This supplements the [original evaluation](investigation-evaluation.md); it does
not replace or erase its failed versions or six passing version-10 trials.

## Frozen scope and acceptance

For the initial cohort, the model, system prompt and structured response policy were
`openai/gpt-oss-120b` / `investigation_v10`. No prompt or thresholds may change
between trials. The owner confirmed Groq Free and authorized this expansion.

| Synthetic incident | Frozen expected category | Required interpretation |
| --- | --- | --- |
| Successful execution with a quality report containing one fail and one pass | `reported_quality_failure` | Explain the reported check outcome without inventing its underlying cause, rule identity or business impact |
| Successful producer execution with an incomplete independent source scan | `source_evidence_gap` | Describe missing monitoring evidence; do not turn it into a confirmed business execution failure |
| Failed and succeeded producer events for the same run and attempt | `conflicting_execution_reports` | Acknowledge incompatible terminal claims, preserve uncertainty and do not select a true winner |

Each case receives **two predeclared trials**. All **six** must complete with
schema/grounding-valid output, the expected category, and a passing manual reading
against the interpretation above. Both trials in each class must agree on the
category. Unsupported abstention, provider failure or omitted conflict fails the
usefulness gate and remains recorded; it is not silently replaced by a new key.
There is no statistical accuracy or confidence-calibration claim from six trials.

The private plan freezes full evidence, bundle/packet hashes, labels, the system
hash and six request keys before any provider request. Its SHA-256 is
`dfd997ca992b81344883d69349d8c566bba29289d54e47ed6e69d6650d986fc1`.
The plan lives under ignored `data/local/investigations/expanded-v10-20261104/`.
It contains operational test data, not learning notes.

## Execution boundary

Fixtures use a distinct `evaluation_` PostgreSQL schema. Normal API ingestion,
quality admission, deterministic detection and evidence capture produce the
bundles. The source scan is an explicitly synthetic reconciler observation.
The schema retains its own immutable request/outcome ledger. No retained business
job, Airflow scheduling, warehouse run or recovery action is used.

Trials use the normal authenticated ASGI routes with the restricted API database
role. Only evaluator-to-local transport uses in-process `TestClient`; the service's
Groq HTTPS transport, projection, grounding, admission checks, durable recording
and exact-key replay remain unchanged. This is not an independent TCP/browser test.
Both the retained and fixture request ledgers count toward the existing 20/day and
60-second limits. At most six new provider attempts are authorized in this plan;
provider quota failure stops further trials. Replays cannot regenerate a response.

After each result, inspect explanation, uncertainty and advisory checks as well as
machine scoring. Check rejection of wrong categories/citations, omitted
contradictions, later-retry conflation and executable commands through the existing
offline suite. Verify frozen evidence hashes, replay stability, retained-row hashes,
source inventory, disabled recovery and paused scheduling before closing the gate.

## Offline preparation

The three complete API fixtures plus existing fixed/adversarial checks passed
**39 cases**. The existing Starlette/HTTPX test-client deprecation warning remains
unsuppressed. No investigator implementation, dependency, migration, prompt or
production configuration changed during preparation.

Official references: [Groq structured outputs](https://console.groq.com/docs/structured-outputs)
and [organization-wide rate limits](https://console.groq.com/docs/rate-limits).
Schema adherence is separate from semantic correctness.

## Initial cohort failure and decoder correction

The initial frozen cohort completed both quality trials and both source-gap trials
safely and usefully. Its first conflict trial failed with
`unsupported_contradiction`; the outcome is durable. The sixth trial was not run.
This is a **failed, incomplete cohort**, not a passing four-of-five benchmark.

The response schema had offered contradiction citations that conflicted with each
other but could not contradict any eligible primary support. The local validator
correctly refused the result. Decoder candidates now must be incompatible with
at least one eligible primary citation. A flag-only reconciliation finding thus
permits `none`; a genuine same-attempt source-failure primary still permits its
incompatible success citation. The validator, categories, model, system prompt,
request options and scoring thresholds are unchanged. A regression covers both
paths, and the focused offline set passes **40 cases**.

A second cohort freezes all six trials again before generation, with new keys,
the same immutable fixtures and explicit per-case response-schema hashes.
Its private plan is `expanded-v10-20261104-r2/plan.json`, SHA-256
`5bce5fa64f7cb01dd0c5266d79f90eda89185e7bd84322beec29bbb94e59259c`.
The first cohort's five requests/outcomes stay in the same isolated ledger and
count toward the same daily limit. No failed request is overwritten or regenerated.
The second-cohort failure is recorded below.

## Second cohort failure and version 11 protocol

The second cohort also passed its four quality/source trials, then failed its
first conflict trial with provider HTTP 400. The sanitized diagnostic reports a
primary citation outside the allowed `e1`/`e4` reconciliation-flag citations.
No invalid output became a finding. Its sixth trial was not run. Both cohorts
remain failed/incomplete with five durable attempts each; they are not pooled
into a passing score.

`investigation_v11` explicitly tells the model to support conflict findings with
a citation that itself has `reconciliation_required=true`, explain incompatible
terminal claims without choosing a winner, and use `none` when the primary flag
is not itself a terminal claim. Model, request options, local validator, fixture
facts and usefulness thresholds remain unchanged. The earlier six-trial version-10
results remain historical; they are not relabeled as version-11 live results.

The version-11 cohort predeclares the same six new-class trials, testing both
conflict trials first, then both quality trials, then both source-gap trials.
This order checks the reproduced failure before spending calls on the other
classes. Its plan is `expanded-v11-20261104/plan.json`, SHA-256
`26539798ceb11bbb32d84df40e37261716a248e0426a9cb39fb3b35e6ba317ca`.
The ten earlier attempts count toward the same 20/day cap; this cohort allows
only six more. No automatic regeneration, fallback or quota bypass is introduced.
The version-11 results follow.


## Final results

All **six version-11 trials passed** machine scoring and manual review: two quality
failures, two source-monitoring gaps and two same-attempt conflicts. Each pair
agreed on its expected category. Conflict explanations explicitly preserved the
failed/succeeded disagreement without selecting a true winner. Quality findings
reported the failed-check summary without inventing a cause. Source-gap findings
did not turn monitoring loss into a confirmed business execution failure.

There were **16 provider attempts across three cohorts**, including the two retained
failed trials. The two five-trial version-10 cohorts remain failed/incomplete; their
four passing trials apiece are not substituted into the six-trial version-11 gate.
All sixteen requests/outcomes replayed unchanged with a provider-call trap, zero
new provider calls and identical native ledger/bundle content hashes. Frozen packet
hashes still match. The isolated schema and an owner-private same-disk archive retain
its history separately from the public application schema.

Current checks pass **441 backend + 48 frontend + 64 workload + 13 Airflow = 566**
cases. The existing Starlette/HTTPX warning remains unsuppressed. All **7,688**
retained baseline rows preserve IDs/content hashes. The public application still
has 16 investigation requests/outcomes; its original evidence was not replaced by
test fixtures. Source inventory remains **8 runs / 14 attempts**, recovery remains
off, and the sample DAG remains paused. API/dashboard were restored and the API
refreshed to version 11; liveness/readiness/dashboard return 200.

### Interpretation limits

These are six small, complete, synthetic packets with real hosted inference, not
real-world root-cause accuracy, calibrated confidence, or unrestricted injection
resistance. Older version-10 results for other classes remain historical; version-11
coverage of those source/lineage/retry/abstention rules is currently offline.
Truncated bundles remain refused. Confidence varied between low and medium and
has no calibrated probability meaning. Next checks were safe but often generic;
quality trials did not select direct quality-report comparison. Source/run wording
was sometimes broad. In-process ASGI verification does not repeat TCP/browser QA.
No automatic recovery, provider fallback, quota increase or paid tier was introduced.

See the [structured report](audit/investigation-expanded-evaluation.json), including
both failed cohorts and all current measurements. Stage 14 remains a separate final
multi-agent audit of this revised code and its product flows.
