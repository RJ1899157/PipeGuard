import { test } from "node:test";
import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { requestSecurity } from "../lib/security.ts";

test("production CSP uses a fresh strong nonce and rejects injected nonce headers", () => {
  const headers = new Headers({
    host: "127.0.0.1:3000",
    "x-nonce": "attacker",
    "content-security-policy": "script-src 'unsafe-inline' 'nonce-attacker'",
  });
  const first = requestSecurity(headers, false);
  const second = requestSecurity(headers, false);
  const nonce = first.requestHeaders.get("x-nonce")!;
  assert.equal(Buffer.from(nonce, "base64").length, 32);
  assert.notEqual(nonce, second.requestHeaders.get("x-nonce"));
  assert.equal(
    first.requestHeaders.get("content-security-policy"),
    first.policy,
  );
  assert.equal(first.requestHeaders.get("host"), "127.0.0.1:3000");
  const script = first.policy
    .split("; ")
    .find((rule) => rule.startsWith("script-src "))!;
  assert.ok(script.includes(`'nonce-${nonce}'`));
  assert.ok(script.includes("'strict-dynamic'"));
  assert.ok(!script.includes("'unsafe-inline'"));
  assert.ok(!script.includes("'unsafe-eval'"));
  assert.ok(first.policy.includes("script-src-attr 'none'"));
  assert.ok(first.policy.includes("style-src 'self' 'unsafe-inline'"));
  assert.ok(first.policy.includes("object-src 'none'"));
  assert.equal(headers.get("x-nonce"), "attacker");
});

test("Next's installed renderer extracts the exact generated nonce", () => {
  const require = createRequire(import.meta.url);
  const {
    getScriptNonceFromHeader,
  } = require("next/dist/server/app-render/get-script-nonce-from-header.js");
  for (const development of [false, true]) {
    const { requestHeaders, policy } = requestSecurity(
      new Headers(),
      development,
    );
    assert.equal(
      getScriptNonceFromHeader(policy),
      requestHeaders.get("x-nonce"),
    );
    assert.equal(policy.includes("'unsafe-eval'"), development);
  }
});
