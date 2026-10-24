/** Exact backend contracts and browser projection parity; no generated rehash approval. */
import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { readFileSync, readdirSync } from "node:fs";

export function checkTechnicalReviewContracts() {
  const root = new URL("../../apps/api/plane/curve/manual_gate2_v3/contract_snapshot/", import.meta.url);
  const raw = (name) => readFileSync(new URL(name, root));
  const read = (name) => JSON.parse(raw(name));
  const hash = (value) => "sha256:" + createHash("sha256").update(value).digest("hex");
  assert.equal(hash(raw("manifest.json")), "sha256:3272d28ee28366a4f8364e44c252c46f9481eb886624afc4abafbd716204f682");
  const manifest = read("manifest.json");
  assert.deepEqual(
    Object.keys(manifest).toSorted(),
    readdirSync(root)
      .filter((n) => n.endsWith(".json") && n !== "manifest.json")
      .toSorted()
  );
  for (const [name, expected] of Object.entries(manifest)) assert.equal(hash(raw(name)), expected, name);
  const expected = Object.fromEntries(
    ["command", "status", "preparation", "material"].map((n) => [n, read(n + ".schema.json")])
  );
  expected.projection = expected.status.properties.current_record.anyOf[0];
  assert.deepEqual(
    JSON.parse(readFileSync(new URL("./src/curve/manual-gate2-v3.schemas.json", import.meta.url))),
    expected
  );
  console.log("Two-stage Technical-review pinned backend contracts and browser projections match.");
}
