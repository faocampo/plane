import { test } from "node:test";
import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { mkdtempSync, writeFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { mergePlan } from "../pre-commit.mjs";

function fixture(t) {
  const cwd = mkdtempSync(join(tmpdir(), "curve-hook-test-"));
  t.after(() => rmSync(cwd, { recursive: true, force: true }));
  const git = (...args) => execFileSync("git", args, { cwd, encoding: "utf8", stdio: "pipe" });
  const put = (path, text) => writeFileSync(join(cwd, path), text);
  git("init", "-b", "main");
  git("config", "user.email", "test@example.invalid");
  git("config", "user.name", "Synthetic Test");
  git("config", "core.hooksPath", "/dev/null");
  put("shared.js", "base\n");
  git("add", ".");
  git("commit", "-m", "base");
  git("checkout", "-b", "upstream");
  put("shared.js", "upstream\n");
  put("space and\nnewline.js", "imported\n");
  git("add", ".");
  git("commit", "-m", "upstream");
  git("checkout", "main");
  put("shared.js", "local\n");
  git("add", ".");
  git("commit", "-m", "local");
  return { cwd, git, put };
}

test("ordinary commits use the original hook path", (t) => {
  assert.equal(mergePlan(fixture(t).cwd), null);
});
test("unresolved merges fail closed", (t) => {
  const f = fixture(t);
  assert.throws(() => f.git("merge", "--no-commit", "upstream"));
  assert.throws(() => mergePlan(f.cwd), /Resolve all conflicts/);
});
test("blob identity separates imports, resolutions and new files with unusual names", (t) => {
  const f = fixture(t);
  assert.throws(() => f.git("merge", "--no-commit", "upstream"));
  f.put("shared.js", "resolved\n");
  f.put("new file.js", "new\n");
  f.git("add", ".");
  assert.deepEqual(mergePlan(f.cwd), { strict: ["new file.js", "shared.js"], imported: 1 });
  f.put("shared.js", "unstaged\n");
  assert.throws(() => mergePlan(f.cwd));
});
test("exact parent resolution retains normal repository checks", (t) => {
  const f = fixture(t);
  assert.throws(() => f.git("merge", "--no-commit", "upstream"));
  f.put("shared.js", "upstream\n");
  f.git("add", ".");
  assert.deepEqual(mergePlan(f.cwd), { strict: [], imported: 2 });
});

test("renamed resolutions remain strict and deleted paths are not passed to tools", (t) => {
  const f = fixture(t);
  assert.throws(() => f.git("merge", "--no-commit", "upstream"));
  f.put("shared.js", "resolved\n");
  f.git("add", ".");
  f.git("mv", "shared.js", "renamed.js");
  f.git("rm", "space and\nnewline.js");
  assert.deepEqual(mergePlan(f.cwd), { strict: ["renamed.js"], imported: 0 });
});
