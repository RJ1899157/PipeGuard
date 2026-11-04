import assert from "node:assert/strict";
import test from "node:test";
import { proposalExpired } from "../lib/use-expiry.ts";

test("both proposal flows expire at the exact deadline without a history refresh", () => {
  const row = { expires_at: "2026-11-04T09:00:00Z", expired: false };
  const deadline = Date.parse(row.expires_at);
  assert.equal(proposalExpired(row, deadline - 1), false);
  assert.equal(proposalExpired(row, deadline), true);
  assert.equal(proposalExpired(row, deadline + 1), true);
  assert.equal(proposalExpired({ ...row, expired: true }, deadline - 1), true);
});

test("malformed proposal expiry fails closed", () => {
  for (const expires_at of ["", "not-a-date", "Infinity"])
    assert.equal(proposalExpired({ expires_at }, Date.now()), true);
});
