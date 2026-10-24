// Copyright (c) 2023-present Plane Software, Inc. and contributors
// SPDX-License-Identifier: AGPL-3.0-only
// See the LICENSE file for details.
import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { readFileSync, readdirSync } from "node:fs";

/** Verify the reviewed backend edition and exact browser copies before generating validators. */
export function checkProductReviewContracts() {
  const backend = new URL("../../apps/api/plane/curve/scoped_prd_v2_candidate/", import.meta.url);
  const browser = new URL("./src/curve/existing-work-contracts/", import.meta.url);
  const read = (name) => readFileSync(new URL(name, backend));
  const digest = (bytes) => "sha256:" + createHash("sha256").update(bytes).digest("hex");
  assert.equal(
    digest(read("manifest-v2.json")),
    "sha256:abf906b6cec6dd39ea128e56b87a75083cafb868923ea8fd549aaefeace22832"
  );
  const manifest = JSON.parse(read("manifest-v2.json"));
  assert.deepEqual(
    Object.keys(manifest).toSorted(),
    readdirSync(backend)
      .filter((n) => n.endsWith(".json") && n !== "manifest-v2.json")
      .toSorted()
  );
  for (const [name, hash] of Object.entries(manifest)) assert.equal(digest(read(name)), hash, name);
  for (const kind of ["observe", "observation", "subject", "submit", "approve", "return-for-revision"]) {
    const name = `scoped-prd-${kind}-v2.schema.json`;
    assert.deepEqual(readFileSync(new URL(name, browser)), read(name), name);
  }
}
