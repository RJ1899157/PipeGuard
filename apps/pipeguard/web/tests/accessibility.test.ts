import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import ts from "typescript";

test("every native selector has a stable name and matching visible label", async () => {
  let count = 0;
  for (const file of ["dashboard", "analytics", "graph-text"]) {
    const source = ts.createSourceFile(
      `${file}.tsx`,
      await readFile(
        new URL(`../components/${file}.tsx`, import.meta.url),
        "utf8",
      ),
      ts.ScriptTarget.Latest,
      true,
      ts.ScriptKind.TSX,
    );
    const selectors = new Map<string, string>();
    const labels = new Set<string>();
    function visit(node: ts.Node) {
      if (ts.isJsxOpeningElement(node)) {
        const attrs = new Map(
          node.attributes.properties.flatMap((attr) =>
            ts.isJsxAttribute(attr) &&
            attr.initializer &&
            ts.isStringLiteral(attr.initializer)
              ? [[attr.name.getText(source), attr.initializer.text] as const]
              : [],
          ),
        );
        if (node.tagName.getText(source) === "label" && attrs.has("htmlFor"))
          labels.add(attrs.get("htmlFor")!);
        if (node.tagName.getText(source) === "select") {
          assert.ok(attrs.get("id"), `${file}: missing selector ID`);
          assert.ok(
            attrs.get("aria-label")?.trim(),
            `${file}: missing selector name`,
          );
          assert.equal(selectors.has(attrs.get("id")!), false);
          selectors.set(attrs.get("id")!, attrs.get("aria-label")!);
          count++;
        }
      }
      ts.forEachChild(node, visit);
    }
    visit(source);
    for (const id of selectors.keys())
      assert.ok(labels.has(id), `${file}: missing label for ${id}`);
  }
  assert.equal(count, 6);
});
