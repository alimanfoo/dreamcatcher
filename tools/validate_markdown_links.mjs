// Validate links in the tracked Markdown files, including unchanged files.
import { execFileSync, spawnSync } from "node:child_process";
import { join } from "node:path";

const [, , verbatimPathsPattern] = process.argv;
if (!verbatimPathsPattern) throw new Error("Expected the verbatim paths pattern.");
const verbatimPaths = new RegExp(verbatimPathsPattern);
const markdownFiles = execFileSync("git", ["ls-files", "-z", "--", "*.md"], {
  encoding: "utf8",
})
  .split("\0")
  .filter((path) => path && !verbatimPaths.test(path));

// pre-commit sets NODE_PATH. Run the CLI directly so filenames pass through
// as arguments on Windows without invoking its .cmd wrapper.
const remark = join(process.env.NODE_PATH, "remark-cli", "cli.js");
const result = spawnSync(
  process.execPath,
  [remark, "--frail", "--quiet", "--no-stdout", "--", ...markdownFiles],
  { stdio: "inherit" },
);
if (result.error) throw result.error;
process.exitCode = result.status ?? 1;
