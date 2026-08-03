#!/usr/bin/env node
/**
 * Validate embedded Mermaid diagrams in Markdown files.
 *
 * Why a script: Mermaid ships no lightweight offline linter. Its real parser
 * (flowchart, sequence, class, ...) only runs in a browser, so we shell out to
 * mermaid-cli (`mmdc`), which renders each fenced ```mermaid block with headless
 * Chromium and exits non-zero on a parse/render error. Rendering goes to a
 * throwaway temp dir -- nothing is written into the repo.
 *
 * Usage: node scripts/lint-mermaid.mjs <file.md> [more.md ...]
 * Wired up as a local pre-commit hook (see .pre-commit-config.yaml); mmdc is
 * provided there via `additional_dependencies`. Override the binary with $MMDC.
 */
import { execFileSync } from "node:child_process";
import { mkdtempSync, rmSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const files = process.argv.slice(2);
if (files.length === 0) process.exit(0);

// Only files that actually contain a mermaid fence -- avoids launching Chromium
// for Markdown with no diagrams.
const FENCE = /^[ \t]*(`{3,}|~{3,})\s*mermaid\b/im;
const targets = files.filter((file) => {
  try {
    return FENCE.test(readFileSync(file, "utf8"));
  } catch {
    return false; // deleted/unreadable -- not this hook's concern
  }
});
if (targets.length === 0) process.exit(0);

// Keep the human-readable Mermaid parse error; drop mmdc's JS stack trace.
function tidy(stderr) {
  const lines = stderr.split("\n");
  const cut = lines.findIndex(
    (l) => /^\s+at\s/.test(l) || /Parser\.parseError\s*\(/.test(l),
  );
  return (cut === -1 ? lines : lines.slice(0, cut)).join("\n").trim();
}

const mmdc = process.env.MMDC || "mmdc";
const work = mkdtempSync(join(tmpdir(), "mermaid-lint-"));
const failures = [];

for (const file of targets) {
  try {
    execFileSync(
      mmdc,
      ["--quiet", "--input", file, "--output", join(work, "out.md")],
      { stdio: ["ignore", "ignore", "pipe"] },
    );
  } catch (err) {
    if (err.code === "ENOENT") {
      rmSync(work, { recursive: true, force: true });
      console.error(
        `mermaid-lint: could not run "${mmdc}". Install @mermaid-js/mermaid-cli ` +
          "or set $MMDC. (Under pre-commit this is provided automatically.)",
      );
      process.exit(2);
    }
    const detail = tidy(err.stderr?.toString() ?? "") || err.message;
    failures.push({ file, detail });
  }
}

rmSync(work, { recursive: true, force: true });

if (failures.length > 0) {
  for (const { file, detail } of failures) {
    console.error(`\n✖ ${file}\n${detail}`);
  }
  console.error(
    `\nmermaid-lint: ${failures.length} file(s) with invalid diagram(s).`,
  );
  process.exit(1);
}
