import assert from "node:assert/strict";
import test from "node:test";
import {
  recoveryDefinitelyRejected,
  recoveryMutation,
  recoveryRead,
} from "../lib/recovery-boundary.ts";
const id = "00000000-0000-0000-0000-000000000001";
const key = "00000000-0000-0000-0000-000000000002";
const propose = { operation: "propose", incident_id: id, request_key: key };
test("recovery broker accepts only fixed review operations", () => {
  assert.equal(
    recoveryMutation(propose)?.path,
    `/v1/incidents/${id}/recovery-proposals`,
  );
  const decision = {
    ...propose,
    operation: "decide",
    proposal_id: id,
    proposal_hash: "a".repeat(64),
    confirmed: true,
    decision: "approve",
  };
  assert.equal(
    recoveryMutation(decision)?.path,
    `/v1/incidents/${id}/recovery-proposals/${id}/decisions`,
  );
  for (const body of [
    null,
    [],
    { ...propose, command: "curl attacker" },
    { ...propose, operation: "execute" },
    { ...propose, incident_id: "../../credentials" },
    { ...propose, request_key: 1 },
    { ...propose, incident_id: id + "\n" },
    { ...propose, request_key: key + "\n" },
    { ...decision, confirmed: 1 },
    { ...decision, confirmed: "true" },
    { ...decision, proposal_hash: "bad" },
    { ...decision, proposal_hash: "a".repeat(64) + "\n" },
    { ...decision, decision: "dispatch" },
    { ...decision, target: "https://attacker.invalid" },
  ])
    assert.equal(recoveryMutation(body), null);
});
test("recovery history has scoped, bounded paths", () => {
  assert.equal(
    recoveryRead(id, null),
    `/v1/incidents/${id}/recovery-proposals?limit=20`,
  );
  assert.equal(
    recoveryRead(id, key),
    `/v1/incidents/${id}/recovery-proposals?limit=20&before=${key}`,
  );
  assert.equal(recoveryRead("https://attacker.invalid", null), null);
  assert.equal(recoveryRead(id, "../other"), null);
});
test("unknown submission outcomes preserve the exact review request", () => {
  for (const code of [
    "database_unavailable",
    "identity_conflict",
    "recovery_connection_unknown",
    503,
    {},
    undefined,
  ])
    assert.equal(recoveryDefinitelyRejected(code), false);
  for (const code of [
    "recovery_evidence_changed",
    "recovery_expired",
    "recovery_busy",
    "recovery_hash_mismatch",
    "administrator_required",
  ])
    assert.equal(recoveryDefinitelyRejected(code), true);
});
