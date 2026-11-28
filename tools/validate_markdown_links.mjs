// Validate links in the tracked Markdown files, including unchanged files.
import { execFileSync, spawnSync } from "node:child_process";
import { join } from "node:path";

const verbatimDirectories = process.argv.slice(2);
const markdownFiles = execFileSync("git", ["ls-files", "-z", "--", "*.md"], {
  encoding: "utf8",
})
  .split("\0")
  .filter(
    (path) => path && !verbatimDirectories.some((directory) => path.startsWith(directory)),
  );

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
