/** Exact backend contracts and browser projection parity; no generated rehash approval. */
import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { readFileSync, readdirSync } from "node:fs";

const root = new URL("../../apps/api/plane/curve/manual_gate2_v2/contract_snapshot/", import.meta.url);
const raw = (name) => readFileSync(new URL(name, root));
const read = (name) => JSON.parse(raw(name));
const hash = (value) => "sha256:" + createHash("sha256").update(value).digest("hex");
assert.equal(hash(raw("manifest.json")), "sha256:72877f8914391b231fe916853faed3c72f5d11456d154b1fe54d9ba6714b8387");
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
assert.deepEqual(JSON.parse(readFileSync(new URL("./src/curve/manual-gate2.schemas.json", import.meta.url))), expected);
console.log("Manual Gate2 pinned backend contracts and browser projections match.");
