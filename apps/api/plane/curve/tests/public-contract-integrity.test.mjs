import assert from "node:assert/strict";
import { cp, mkdtemp, readFile, rm, symlink, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { pathToFileURL } from "node:url";
import { createHash } from "node:crypto";
import test from "node:test";
import { validateConsumerSnapshot } from "../contracts/check-integrity.mjs";

const source = new URL("../contracts/", import.meta.url);

async function isolated(t) {
  const path = await mkdtemp(join(tmpdir(), "curve-public-integrity-test-"));
  t.after(() => rm(path, { recursive: true, force: true }));
  await cp(source, path, { recursive: true });
  return pathToFileURL(path + "/");
}

test("complete public consumer bundle is pinned without execution authority", async () => {
  const result = await validateConsumerSnapshot();
  assert.equal(result.files, 109);
  assert.equal(result.edition, "curve-plane-public-contracts-v1");
  assert.equal(result.execution_authority, "NONE");
});

test("changed contract bytes fail the retained digest guard", async (t) => {
  const root = await isolated(t);
  await writeFile(new URL("schemas/common.schema.json", root), "{}\n");
  await assert.rejects(validateConsumerSnapshot(root), /Contract digest mismatch/);
});

test("additional and missing contracts fail inventory checks", async (t) => {
  const root = await isolated(t),
    extra = new URL("unreviewed.json", root);
  await writeFile(extra, "{}\n");
  await assert.rejects(validateConsumerSnapshot(root), /inventory mismatch/);
  await rm(extra);
  await rm(new URL("schemas/common.schema.json", root));
  await assert.rejects(validateConsumerSnapshot(root), /inventory mismatch/);
});

test("contract symlinks cannot escape the pinned bundle", async (t) => {
  const root = await isolated(t),
    target = new URL("schemas/common.schema.json", root);
  await rm(target);
  await symlink(new URL("schemas/common.schema.json", source), target);
  await assert.rejects(validateConsumerSnapshot(root), /symlinks are prohibited/);
});

test("rewritten file and manifest hashes cannot silently repin validation", async (t) => {
  const root = await isolated(t),
    target = new URL("schemas/common.schema.json", root);
  const body = "{}\n";
  await writeFile(target, body);
  const manifestPath = new URL("public-consumer-edition-v1.json", root);
  const manifest = JSON.parse(await readFile(manifestPath));
  manifest.files.find((file) => file.path === "schemas/common.schema.json").sha256 = createHash("sha256")
    .update(body)
    .digest("hex");
  await writeFile(manifestPath, JSON.stringify(manifest, null, 2) + "\n");
  await assert.rejects(validateConsumerSnapshot(root), /manifest digest mismatch/);
});

test("historical public contexts cannot be turned into human execution grants", async (t) => {
  const root = await isolated(t),
    target = new URL("m1-01a-context.json", root);
  const context = JSON.parse(await readFile(target));
  context.execution_authority = "ALLOW";
  context.approval_evidence = { actor: "forged-example-reviewer" };
  await writeFile(target, JSON.stringify(context));
  await assert.rejects(validateConsumerSnapshot(root), /Contract digest mismatch/);
});

test("local provider constraints remain pinned against broadened network access", async (t) => {
  const root = await isolated(t),
    target = new URL("providers/m0-s9a-provider-registry-v1.json", root);
  const manifest = JSON.parse(await readFile(target));
  manifest.authority.external_network = "ENABLED";
  await writeFile(target, JSON.stringify(manifest));
  await assert.rejects(validateConsumerSnapshot(root), /Contract digest mismatch/);
});
