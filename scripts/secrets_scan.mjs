#!/usr/bin/env node
// Gate step (M11, hard rule 9): no secrets in git. Scans every tracked text file for things that
// look like keys. The local development passwords in .env.example are not secrets and are allowed.
import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const PATTERNS = [
  ["API key (sk-...)", /\bsk-[A-Za-z0-9_-]{20,}/],
  ["private key block", /-----BEGIN [A-Z ]*PRIVATE KEY-----/],
  ["GitHub token", /\bgh[pousr]_[A-Za-z0-9]{30,}/],
  ["hosted database URL with a password", /postgres(?:ql)?:\/\/[^:\s"'`]+:[^@\s"'`$<]{8,}@[^\s"'`]*(neon\.tech|render\.com|supabase\.co)/],
  ["key assigned a value", /\b(DEEPSEEK_API_KEY|ANTHROPIC_API_KEY|ENGINE_WEB_KEY)\s*=\s*[A-Za-z0-9_-]{16,}/],
];
const BINARY = /\.(png|jpe?g|gif|webp|ico|stl|3mf|gz|zip|mp4|webm|woff2?|pdf)$/i;

const files = execFileSync("git", ["ls-files"], { cwd: ROOT, encoding: "utf8" }).split("\n").filter(Boolean);
const found = [];
for (const file of files) {
  if (BINARY.test(file) || file === "scripts/secrets_scan.mjs") continue;
  let text;
  try {
    text = readFileSync(join(ROOT, file), "utf8");
  } catch {
    continue;
  }
  text.split("\n").forEach((line, i) => {
    for (const [what, re] of PATTERNS) if (re.test(line)) found.push(`${file}:${i + 1}: ${what}`);
  });
}
if (found.length) {
  console.error("✗ Possible secrets in tracked files (values not shown):\n  " + found.join("\n  "));
  process.exit(1);
}
console.log(`No secrets found in ${files.length} tracked files.`);
