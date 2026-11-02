# Investigation evaluation gate

Protocol frozen on 2026-11-02 before the first `investigation_v8` trial. The same thresholds and evidence apply to the separately versioned `investigation_v9` and `investigation_v10` evaluations.

## Acceptance criteria

The gate measures the bounded **local advisory** feature. It does not establish root-cause accuracy, calibrated confidence, production-model reliability or recovery safety.

1. Every fixed offline reference and adversarial check must pass. Unsupported categories/citations, executable next checks and omitted same-attempt contradictory terminal evidence must be rejected. A successful later retry must remain recovery context.
2. Freeze three existing sample incidents into immutable evidence bundles: failed execution followed by successful retry, partial lineage and missing quality reports. Record bundle/packet hashes, expected source-claim categories and two distinct request keys per case before running anything. Expected labels are reviewed from the machine facts; they are not independently established root causes.
3. Run exactly two trials per case through the normal durable API. No direct provider invocation, changed prompts between trials, automatic retry, fallback or budget bypass. Admission failures remain visible and do not justify regenerating a trial key.
4. Require all six trials to finish with locally valid safe output, all missing-quality trials to abstain without a provider call, and at least 80% of the four supported-finding trials to produce the expected category. With this small set, this means all four must be useful. Repeat agreement is category/abstention agreement, not identical prose.
5. Keep the model provisional if the set fails. The provider must remain on the operator-confirmed Free plan; quota exhaustion stops new trials. A passing local gate still cannot authorize recovery or establish performance on untested incident classes.

## Reproduction and interruption handling

The owner-private plans live under ignored `data/local/investigations/evaluation-v8/plan.json`, `evaluation-v9/plan.json` and `evaluation-v10/plan.json`. Each freezes real bundle identifiers/hashes, projected packet hashes, labels and two request keys for each case. This is operational evaluation data, not personal learning material. No source history is changed or removed.

Run a single predeclared trial (case indexes 0–2; trial 1 or 2):

```sh
uv run --locked --env-file .env python scripts/evaluate_investigations.py \
  --plan data/local/investigations/evaluation-v10/plan.json \
  --case 0 --trial 1 --free-plan-confirmed
```

Allow the existing one-minute global cooldown between new submissions. Each result file is written atomically; interruption is resolved by rerunning the same command and replaying the already frozen request key. The request and provider contract remain in the normal database ledger. Replaying does not create another provider call.

Run the fixed offline checks without Groq calls:

```sh
uv run --locked --env-file .env pytest -q apps/pipeguard/tests/test_investigation_evaluation.py
```

## Coverage limits

Offline cases cover source/execution/validation failures, quality fail/error reports, source scan gaps, lineage gaps, unsupported/missing facts, contradictory terminal states, later retries, unrelated runs and malformed/adversarial outputs. Existing projection checks inject hostile arbitrary text into source bundles and verify it never leaves the projection. This tests the enforced data boundary; it does not estimate unrestricted prompt-injection resistance.

The live set covers only three existing incident types. The existing source-coverage incident produces a truncated bundle and is **excluded before trials** because projection correctly refuses it. Live quality-failure, source-coverage and same-attempt contradiction scenarios remain required before extending claims to those classes. Scoring labels directly reported facts; arbitrary generated prose is unverified and stays collapsed in the UI. Both confidence labels remain uncalibrated.

Groq lists Qwen as a preview model. After its failed evaluations below, version 10 explicitly selects `openai/gpt-oss-120b`, listed by Groq as a production model with strict structured-output support. Authenticated model availability was checked before generation. This still uses Groq and the operator-confirmed Free organization; no OpenAI API credential, paid plan or automatic fallback is involved. Use low reasoning effort and a 4,096-token completion bound, including reasoning tokens. See [Groq's supported models](https://console.groq.com/docs/models), [structured-output documentation](https://console.groq.com/docs/structured-outputs) and [OpenAI's model reference](https://developers.openai.com/api/docs/models/gpt-oss-120b). A future model change must repeat the fixed gate.

## Results

Version 8 failed its usefulness gate: execution trial 1 produced the expected source-failure finding, but lineage trial 1 abstained after focusing on the prior execution failure rather than the selected lineage incident. Remaining version 8 trials were stopped after this failure; this is an incomplete failed run, not a passing six-trial benchmark. Both admitted results remain in the database. One earlier submission was refused by the local cooldown before admission; it made no provider call.

Version 9 clarified that a metadata-coverage incident should be explained as a reported coverage gap, without claiming it caused an execution failure. Its lineage trial passed, but execution trial 1 failed with provider HTTP 400 (JSON generation failure). Remaining trials were stopped; this is another incomplete failed evaluation. No automatic regeneration was attempted.

Version 10 changes the model and model-specific reasoning/completion settings, preserving the version 9 prompt, source evidence and thresholds. Results are pending; criteria must not be loosened to fit observed output.
