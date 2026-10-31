import { test } from "node:test";
import assert from "node:assert/strict";
import { localRequestAllowed, readPath } from "../lib/boundary.ts";
const id = "00000000-0000-4000-8000-000000000001";
test("only local exact host and same origin are accepted", () => {
  for (const host of ["127.0.0.1:3000", "localhost:3000"]) {
    assert.equal(localRequestAllowed(new Headers({ host })), true);
    assert.equal(
      localRequestAllowed(
        new Headers({
          host,
          origin: `http://${host}`,
          "sec-fetch-site": "same-origin",
        }),
      ),
      true,
    );
  }
  for (const extra of [
    { host: "evil.test:3000" },
    { host: "127.0.0.1:3000.evil.test" },
    { host: "localhost:3000", origin: "https://evil.test" },
    { host: "localhost:3000", "sec-fetch-site": "cross-site" },
    { host: "localhost:3000", "sec-fetch-site": "same-site" },
    {},
  ])
    assert.equal(
      localRequestAllowed(new Headers(extra as Record<string, string>)),
      false,
    );
});
test("read broker is an explicit fixed-path allowlist", () => {
  for (const kind of [
    "credentials",
    "integrations",
    "acknowledge",
    "events",
    "https://evil.test",
    "../integrations",
  ])
    assert.equal(readPath(new URLSearchParams({ kind, id })), null);
  assert.equal(
    readPath(new URLSearchParams({ kind: "coverage" })),
    "/v1/monitoring/coverage",
  );
  assert.equal(
    readPath(new URLSearchParams({ kind: "attempts", id })),
    `/v1/runs/${id}/attempts?limit=50&offset=0`,
  );
  assert.equal(
    readPath(new URLSearchParams({ kind: "lineage-event", id })),
    `/v1/lineage-events/${id}`,
  );
});
test("invalid identifiers, bounds and traversal attempts are rejected", () => {
  for (const value of [
    "../credentials",
    "x",
    "http://evil.test",
    id + "/process",
  ])
    assert.equal(
      readPath(new URLSearchParams({ kind: "attempts", id: value })),
      null,
    );
  for (const offset of ["-1", "1.5", "NaN", "100001"])
    assert.equal(readPath(new URLSearchParams({ kind: "jobs", offset })), null);
  for (const attempt of ["0", "-1", "1.1", "Infinity", "2147483648"])
    assert.equal(
      readPath(
        new URLSearchParams({ kind: "lineage", id, run: "run", attempt }),
      ),
      null,
    );
  assert.equal(
    readPath(
      new URLSearchParams({
        kind: "lineage",
        id,
        run: "a".repeat(256),
        attempt: "1",
      }),
    ),
    null,
  );
});
test("execution scope is encoded, never interpreted as a destination", () => {
  const path = readPath(
    new URLSearchParams({
      kind: "lineage",
      id,
      run: "run&attempt_number=999?/#",
      attempt: "2",
    }),
  );
  const url = new URL(path!, "http://127.0.0.1:8000");
  assert.equal(url.origin, "http://127.0.0.1:8000");
  assert.equal(
    url.searchParams.get("external_run_id"),
    "run&attempt_number=999?/#",
  );
  assert.deepEqual(url.searchParams.getAll("attempt_number"), ["2"]);
});
test("quality read scope retains pagination and the complete API attempt range", () => {
  const path = readPath(
    new URLSearchParams({
      kind: "quality",
      id,
      run: "run-1",
      attempt: "2147483647",
      offset: "50",
    }),
  );
  const url = new URL(path!, "http://127.0.0.1:8000");
  assert.equal(url.pathname, `/v1/jobs/${id}/quality-reports`);
  assert.equal(url.searchParams.get("attempt_number"), "2147483647");
  assert.equal(url.searchParams.get("offset"), "50");
  assert.equal(
    readPath(
      new URLSearchParams({
        kind: "quality",
        id,
        run: "run-1",
        attempt: "2147483648",
      }),
    ),
    null,
  );
});

test("snapshot cursors stay bounded and only reach supported read lists", () => {
  for (const snapshot of ["new", "a".repeat(43)]) {
    const path = readPath(
      new URLSearchParams({ kind: "jobs", offset: "50", snapshot }),
    );
    assert.equal(
      new URL(path!, "http://127.0.0.1:8000").searchParams.get("snapshot"),
      snapshot,
    );
  }
  for (const snapshot of [
    "",
    "../events",
    "https://evil.test",
    "a".repeat(129),
  ])
    assert.equal(
      readPath(new URLSearchParams({ kind: "jobs", snapshot })),
      null,
    );
  for (const kind of ["coverage", "lineage", "lineage-event"])
    assert.equal(
      readPath(
        new URLSearchParams({
          kind,
          id,
          run: "run",
          attempt: "1",
          snapshot: "new",
        }),
      ),
      null,
    );
});

test("top-level local document visits work without allowing cross-site data access", async () => {
  const { localDocumentAllowed } = await import("../lib/boundary.ts");
  const headers = new Headers({
    host: "127.0.0.1:3000",
    "sec-fetch-site": "cross-site",
    "sec-fetch-mode": "navigate",
    "sec-fetch-dest": "document",
  });
  assert.equal(localRequestAllowed(headers), false);
  assert.equal(localDocumentAllowed(headers, "GET", "/"), true);
  for (const [method, path] of [
    ["POST", "/"],
    ["GET", "/api/read"],
    ["GET", "/api/watchdog"],
  ])
    assert.equal(localDocumentAllowed(headers, method, path), false);
  for (const [key, value] of [
    ["host", "evil.test"],
    ["origin", "https://evil.test"],
    ["sec-fetch-dest", "iframe"],
    ["sec-fetch-mode", "cors"],
  ]) {
    const bad = new Headers(headers);
    bad.set(key, value);
    assert.equal(localDocumentAllowed(bad, "GET", "/"), false);
  }
});
