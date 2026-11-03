import assert from "node:assert/strict";
import test from "node:test";
import {
  actionMutation,
  actionRead,
  actionDefinitelyRejected,
  type ActionRequest,
} from "../lib/recovery-actions-boundary.ts";
const id = "00000000-0000-0000-0000-000000000001",
  key = "00000000-0000-0000-0000-000000000002";
const start: ActionRequest = {
  operation: "dispatch",
  incident_id: id,
  action_id: id,
  request_key: key,
  proposal_hash: "a".repeat(64),
  confirmed: true,
};
test("executable operations have exact independent routes and body allowlists", () => {
  assert.equal(
    actionMutation(start)?.path,
    `/v1/incidents/${id}/recovery-actions/${id}/dispatch`,
  );
  assert.equal(
    actionMutation({ ...start, operation: "decide", decision: "cancel" })?.path,
    `/v1/incidents/${id}/recovery-actions/${id}/decisions`,
  );
  assert.equal(
    actionMutation({ operation: "propose", incident_id: id, request_key: key })
      ?.path,
    `/v1/incidents/${id}/recovery-actions`,
  );
  assert.equal(
    actionMutation({
      operation: "reconcile",
      incident_id: id,
      action_id: id,
      request_key: key,
    })?.path,
    `/v1/incidents/${id}/recovery-actions/${id}/reconcile`,
  );
  for (const value of [
    null,
    [],
    { ...start, operation: "execute" },
    { ...start, confirmed: 1 },
    { ...start, confirmed: "true" },
    { ...start, action_id: id + "\n" },
    { ...start, proposal_hash: "a".repeat(64) + "\n" },
    { ...start, command: "curl" },
    { ...start, decision: "approve" },
    { ...start, endpoint: "https://attacker.invalid" },
    { ...start, operation: "decide", decision: "dispatch" },
  ])
    assert.equal(actionMutation(value), null);
});
test("executable history is bounded and scoped", () => {
  assert.equal(
    actionRead(id, null),
    `/v1/incidents/${id}/recovery-actions?limit=5`,
  );
  assert.equal(
    actionRead(id, key),
    `/v1/incidents/${id}/recovery-actions?limit=5&before=${key}`,
  );
  assert.equal(actionRead("../other", null), null);
  assert.equal(actionRead(id, id + "\n"), null);
});
test("uncertain dispatch errors retain exact keys even when another command is busy", () => {
  for (const code of [
    "recovery_worker_unknown",
    "database_unavailable",
    "identity_conflict",
    "recovery_busy",
    "recovery_hash_mismatch",
    "recovery_lock_lost",
    "recovery_history_limit",
    null,
    503,
  ])
    assert.equal(actionDefinitelyRejected(start, code), false);
  assert.equal(
    actionDefinitelyRejected(start, "recovery_execution_disabled"),
    true,
  );
  assert.equal(actionDefinitelyRejected(start, "recovery_expired"), true);
  assert.equal(
    actionDefinitelyRejected(
      { ...start, operation: "reconcile" },
      "recovery_expired",
    ),
    false,
  );
});
