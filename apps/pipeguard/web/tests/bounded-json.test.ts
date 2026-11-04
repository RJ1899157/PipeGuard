import assert from "node:assert/strict";
import test from "node:test";
import { boundedJSON } from "../lib/bounded-json.ts";

function stream(chunks: Uint8Array[]) {
  return new ReadableStream<Uint8Array>({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(chunk);
      controller.close();
    },
  });
}

test("bounded JSON counts bytes and decodes split UTF-8 at the exact cap", async () => {
  const value = { text: "Evidence 🔎" };
  const bytes = new TextEncoder().encode(JSON.stringify(value));
  assert.deepEqual(
    await boundedJSON(
      stream([...bytes].map((byte) => Uint8Array.of(byte))),
      bytes.length,
    ),
    value,
  );
  await assert.rejects(
    boundedJSON(stream([bytes]), bytes.length - 1),
    /body_limit/,
  );
});

test("oversized read responses cancel their stream before parsing", async () => {
  let cancelled = false;
  const bytes = new Uint8Array(16 * 1024 * 1024 + 1);
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      controller.enqueue(bytes);
    },
    cancel() {
      cancelled = true;
    },
  });
  await assert.rejects(boundedJSON(body, 16 * 1024 * 1024), /body_limit/);
  assert.equal(cancelled, true);
});

test("missing, malformed and invalid UTF-8 bodies fail closed", async () => {
  await assert.rejects(boundedJSON(null, 100), /missing_body/);
  await assert.rejects(
    boundedJSON(stream([new TextEncoder().encode("not JSON")]), 100),
    SyntaxError,
  );
  await assert.rejects(
    boundedJSON(stream([Uint8Array.of(0xff)]), 100),
    TypeError,
  );
});

test("stalled reads time out even if source cancellation never finishes", async () => {
  let cancelled = false;
  const body = new ReadableStream<Uint8Array>({
    cancel() {
      cancelled = true;
      return new Promise<void>(() => {});
    },
  });
  await assert.rejects(boundedJSON(body, 100, 20), /body_timeout/);
  assert.equal(cancelled, true);
});

test("trickling bytes do not reset the absolute body deadline", async () => {
  let chunks = 0;
  let cancelled = false;
  const body = new ReadableStream<Uint8Array>({
    async pull(controller) {
      await new Promise((resolve) => setTimeout(resolve, 5));
      if (!cancelled) {
        chunks += 1;
        controller.enqueue(Uint8Array.of(32));
      }
    },
    cancel() {
      cancelled = true;
    },
  });
  await assert.rejects(boundedJSON(body, 10000, 30), /body_timeout/);
  assert.equal(cancelled, true);
  assert.ok(chunks < 100);
});
