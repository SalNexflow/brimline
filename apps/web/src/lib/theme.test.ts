import { readFileSync } from "node:fs";
import path from "node:path";

import { expect, test } from "vitest";

// theme.css writes each colour once as light-dark(light, dark), and repeats the light values in a
// fallback block for browsers without light-dark(). The two lists must not drift apart.
const css = readFileSync(path.join(__dirname, "..", "app", "theme.css"), "utf8");

function declarations(block: string): Map<string, string> {
  return new Map([...block.matchAll(/^\s*(--[\w-]+):\s*([^;]+);/gm)].map((m) => [m[1]!, m[2]!.trim()]));
}

test("the fallback block holds exactly the light value of every light/dark colour", () => {
  const pairs = new Map(
    [...css.matchAll(/^ {2}(--[\w-]+): light-dark\((.+?), (#[0-9a-f]{6}|rgb\([^)]*\))\);$/gm)].map((m) => [m[1]!, m[2]!]),
  );
  const fallbackBlock = css.slice(css.indexOf("@supports not (color: light-dark("), css.indexOf("/* Reduced motion"));
  const fallback = declarations(fallbackBlock);
  fallback.delete("--shadow-card"); // written out by hand: its light layers, without the dark-only one
  expect(pairs.size).toBeGreaterThan(30);
  expect(Object.fromEntries(fallback)).toEqual(Object.fromEntries(pairs));
});
