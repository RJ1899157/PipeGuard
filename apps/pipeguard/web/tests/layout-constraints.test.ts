import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import { performanceGraph } from "../lib/exploration-fixtures.ts";

const css = await readFile(
  new URL("../app/globals.css", import.meta.url),
  "utf8",
);
function block(selector: string) {
  const escaped = selector.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const found = css.match(new RegExp(`${escaped}\\s*\\{([^}]+)\\}`));
  assert.ok(found, `Missing style block: ${selector}`);
  return found[1];
}

test("dense graph fixtures exercise valid 255-character names without changing scope", () => {
  for (const cycle of [false, true]) {
    const graph = performanceGraph(cycle);
    assert.equal(graph.nodes.length, 200);
    assert.equal(graph.edges.length, cycle ? 200 : 1000);
    assert.equal(graph.nodes[0].name.length, 255);
    assert.equal(graph.nodes[1].name.length, 255);
    assert.equal(graph.nodes[0].id, "dataset:fixture-0");
    assert.equal(graph.nodes[1].id, `${cycle ? "step" : "dataset"}:fixture-1`);
  }
});

test("diagram labels have a bounded visual height while full names remain available", async () => {
  const label = block(".lineage-node strong");
  assert.match(label, /-webkit-line-clamp:\s*3/);
  assert.match(label, /line-height:\s*1\.3/);
  assert.match(label, /max-height:\s*3\.9em/);
  assert.match(label, /overflow:\s*hidden/);
  const source = await readFile(
    new URL("../components/lineage.tsx", import.meta.url),
    "utf8",
  );
  assert.match(source, /<strong title=\{node\.name\}>\{node\.name\}<\/strong>/);
  assert.ok(source.includes("ariaLabel: `${n.kind}: ${n.name}`"));
  const text = block(".text-alternative button");
  assert.match(text, /max-width:\s*100%/);
  assert.match(text, /overflow-wrap:\s*anywhere/);
});

function luminance(hex: string) {
  const values = [1, 3, 5].map((offset) => {
    const value = parseInt(hex.slice(offset, offset + 2), 16) / 255;
    return value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4;
  });
  return values[0] * 0.2126 + values[1] * 0.7152 + values[2] * 0.0722;
}

test("small footer and attribution text meet normal-text contrast on their backgrounds", () => {
  const muted = css.match(/--muted:\s*(#[0-9a-f]{6})/i)![1];
  const background = css.match(/--bg:\s*(#[0-9a-f]{6})/i)![1];
  for (const selector of [".page-footer", ".react-flow__attribution a"])
    assert.match(block(selector), /color:\s*var\(--muted\)/);
  for (const color of [background, "#ffffff"])
    assert.ok((luminance(color) + 0.05) / (luminance(muted) + 0.05) >= 4.5);
});
