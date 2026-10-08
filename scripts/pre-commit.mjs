import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { pathToFileURL } from "node:url";

const git = (cwd, ...args) => execFileSync("git", args, { cwd, encoding: "utf8" });

function entries(output) {
  return new Map(
    output
      .split("\0")
      .filter(Boolean)
      .map((record) => {
        const tab = record.indexOf("\t");
        return [record.slice(tab + 1), record.slice(0, tab)];
      })
  );
}

export function mergePlan(cwd) {
  const mergePath = git(cwd, "rev-parse", "--git-path", "MERGE_HEAD").trim();
  let heads;
  try {
    heads = readFileSync(new URL(mergePath, pathToFileURL(`${cwd}/`)), "utf8")
      .trim()
      .split("\n");
  } catch (error) {
    if (error.code === "ENOENT") return null;
    throw error;
  }
  if (heads.length !== 1 || !/^[a-f0-9]{40,64}$/.test(heads[0])) {
    throw new Error("Only a two-parent merge is supported by the merge-aware hook.");
  }
  if (git(cwd, "ls-files", "--unmerged", "-z")) throw new Error("Resolve all conflicts before committing.");
  // Check the complete tracked worktree, so checks cannot validate unstaged content.
  git(cwd, "diff", "--exit-code", "--quiet");
  const indexTree = git(cwd, "write-tree").trim();
  const index = entries(git(cwd, "ls-tree", "-r", "-z", indexTree));
  const parents = ["HEAD", heads[0]].map((ref) => entries(git(cwd, "ls-tree", "-r", "-z", ref)));
  const changed = git(cwd, "diff", "--cached", "--name-only", "--diff-filter=ACMRT", "-z").split("\0").filter(Boolean);
  const strict = changed.filter((path) => !parents.some((parent) => parent.get(path) === index.get(path)));
  return { strict, imported: changed.length - strict.length };
}

export function run(cwd = process.cwd()) {
  const plan = mergePlan(cwd);
  if (!plan) {
    execFileSync("pnpm", ["lint-staged"], { cwd, stdio: "inherit" });
    return;
  }
  console.log(`Merge checks: ${plan.strict.length} resolution files; ${plan.imported} unchanged parent files.`);
  // Imported code must meet the repository's existing lint budgets.
  execFileSync("pnpm", ["check:lint"], { cwd, stdio: "inherit" });
  const formatted = plan.strict.filter((path) => /\.(?:[cm]?[jt]sx?|json|css|md)$/.test(path));
  const scripts = plan.strict.filter((path) => /\.[cm]?[jt]sx?$/.test(path));
  // Read-only checks preserve the staged snapshot and never restage user files.
  for (const [tool, options, paths] of [
    ["oxfmt", ["--check", "--no-error-on-unmatched-pattern"], formatted],
    ["oxlint", ["--deny-warnings"], scripts],
  ]) {
    for (let offset = 0; offset < paths.length; offset += 50) {
      execFileSync("pnpm", ["exec", tool, ...options, "--", ...paths.slice(offset, offset + 50)], {
        cwd,
        stdio: "inherit",
      });
    }
  }
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) run();
