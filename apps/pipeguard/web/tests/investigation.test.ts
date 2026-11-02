import assert from "node:assert/strict";
import test from "node:test";
import { submissionDefinitelyRejected } from "../lib/investigation-boundary.ts";

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
