import { test } from "node:test";
import assert from "node:assert/strict";
import { parseWatchdog, watchdogFresh } from "../lib/watchdog.ts";
const state = {
  version: 1,
  checked_at: "2026-10-31T17:00:00Z",
  status: { api: "healthy", database: "healthy", monitor: "fresh" },
  notification: "disabled",
};
test("watchdog boundary rejects malformed data and strips extra private fields", () => {
  assert.deepEqual(parseWatchdog({ ...state, private: "discard" }), state);
  for (const value of [
    null,
    {},
    [],
    { ...state, version: 2 },
    { ...state, checked_at: "invalid" },
    { ...state, status: { ...state.status, api: "invented" } },
    { ...state, status: { ...state.status, api: ["healthy"] } },
    { ...state, status: { ...state.status, database: ["healthy"] } },
    { ...state, status: { ...state.status, monitor: ["fresh"] } },
    { ...state, notification: ["disabled"] },
  ])
    assert.equal(parseWatchdog(value), null);
});
test("watchdog cannot claim fresh health after staleness or future clock skew", () => {
  const parsed = parseWatchdog(state)!;
  const time = Date.parse(state.checked_at);
  assert.equal(watchdogFresh(parsed, time), true);
  assert.equal(watchdogFresh(parsed, time + 45000), true);
  assert.equal(watchdogFresh(parsed, time + 45001), false);
  assert.equal(watchdogFresh(parsed, time - 30001), false);
});
