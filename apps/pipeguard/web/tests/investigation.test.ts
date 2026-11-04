import assert from "node:assert/strict";
import test from "node:test";
import {
  investigationId,
  investigationSubmission,
  submissionDefinitelyRejected,
} from "../lib/investigation-boundary.ts";

test("investigation admission accepts exact identifiers and literal consent only", () => {
  const id = "00000000-0000-4000-8000-000000000001";
  const request = {
    incident_id: id,
    request_key: id,
    free_plan_confirmed: true,
  };
  assert.deepEqual(investigationSubmission(request), {
    id,
    body: JSON.stringify({ request_key: id, free_plan_confirmed: true }),
  });
  assert.equal(investigationId(id), true);
  for (const invalid of [id + "\n", id + "\r\n", "../credentials", 1, null]) {
    assert.equal(investigationId(invalid), false);
    assert.equal(
      investigationSubmission({ ...request, incident_id: invalid }),
      null,
    );
    assert.equal(
      investigationSubmission({ ...request, request_key: invalid }),
      null,
    );
  }
  for (const invalid of [
    null,
    [],
    { ...request, free_plan_confirmed: "true" },
    { ...request, free_plan_confirmed: false },
    { ...request, model: "unapproved-model" },
    { ...request, target: "https://attacker.invalid" },
  ])
    assert.equal(investigationSubmission(invalid), null);
});

test("uncertain database/network outcomes retain the submission key", () => {
  for (const code of [
    "database_unavailable",
    "identity_conflict",
    "investigation_connection_unknown",
    "Internal Server Error",
    undefined,
    {},
    503,
  ])
    assert.equal(submissionDefinitelyRejected(code), false);
});
test("known admission failures permit an explicitly new request", () => {
  for (const code of [
    "investigation_busy",
    "investigation_pending",
    "investigation_cooldown",
    "investigation_daily_limit",
    "administrator_required",
    "invalid_request",
  ])
    assert.equal(submissionDefinitelyRejected(code), true);
});
