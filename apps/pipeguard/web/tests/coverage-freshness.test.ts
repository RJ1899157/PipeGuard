import assert from "node:assert/strict";
import test from "node:test";
import { coverageSampleFresh } from "../lib/coverage-freshness.ts";

const at = "2026-11-04T10:00:00Z";
const captured = Date.parse(at);
const sample = { at, observedMonotonic: 1000 };

test("cached coverage expires after 90 seconds on either clock", () => {
  assert.equal(coverageSampleFresh(sample, captured, 1000), true);
  assert.equal(coverageSampleFresh(sample, captured + 90000, 91000), true);
  assert.equal(coverageSampleFresh(sample, captured + 90001, 91000), false);
  assert.equal(coverageSampleFresh(sample, captured + 90000, 91001), false);
});

test("wall-clock rollback, freezing or slowing cannot extend cached health", () => {
  assert.equal(coverageSampleFresh(sample, captured - 3600000, 2000), false);
  assert.equal(coverageSampleFresh(sample, captured, 91001), false);
  assert.equal(coverageSampleFresh(sample, captured + 10000, 91001), false);
  assert.equal(coverageSampleFresh(sample, captured + 90001, 2000), false);
});

test("missing, future, malformed and inconsistent samples fail closed", () => {
  assert.equal(coverageSampleFresh(null, captured, 1000), false);
  assert.equal(coverageSampleFresh(sample, captured - 1, 1000), false);
  assert.equal(coverageSampleFresh(sample, captured, 999), false);
  assert.equal(
    coverageSampleFresh({ ...sample, at: "invalid" }, captured, 1000),
    false,
  );
  assert.equal(coverageSampleFresh(sample, Infinity, 1000), false);
  assert.equal(coverageSampleFresh(sample, captured, Infinity), false);
});
