// The video's sound effects, made from formulas with the repo's ffmpeg (no downloads, no licence to
// track). Each sound is a short synthesised tone or noise burst with a decaying envelope; the
// formulas are fixed, so every run writes the same files. Writes public/sfx/*.wav (git-ignored).
import { spawnSync } from "node:child_process";
import { mkdirSync } from "node:fs";
import { createRequire } from "node:module";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const OUT = join(ROOT, "public", "sfx");
// ffmpeg-static is already a dependency of the web app (used for its screenshots); reuse it.
const ffmpeg = createRequire(join(ROOT, "..", "apps", "web", "package.json"))("ffmpeg-static");

const RATE = 48000;
// t is seconds; random(0) is ffmpeg's seeded noise (the same every run).
const noise = "(2*random(0)-1)";

/** name -> [length in seconds, ffmpeg aevalsrc formula, optional filter chain] */
const SOUNDS = {
  // A small item appears: a short, high, soft ping.
  tick: [0.08, "0.35*sin(2*PI*2400*t)*exp(-80*t)"],
  // A button press: a bright tap with a little noise on the attack.
  click: [0.06, `0.5*sin(2*PI*1500*t)*exp(-110*t)+0.3*${noise}*exp(-350*t)`],
  // A chip or card lands: a quick upward chirp.
  pop: [0.14, "0.5*sin(2*PI*(380*t+5500*t*t))*exp(-32*t)"],
  // Zooms and panels: filtered noise that swells and fades.
  whoosh: [0.5, `0.9*${noise}*pow(sin(PI*t/0.5),2)`, "highpass=f=250,lowpass=f=2200"],
  swish: [0.28, `0.9*${noise}*pow(sin(PI*t/0.28),2)`, "highpass=f=600,lowpass=f=4000"],
  // Typing: a noisy tap over a low knock; three variants so a run of keys does not sound mechanical.
  key1: [0.05, `0.35*${noise}*exp(-170*t)+0.3*sin(2*PI*170*t)*exp(-70*t)`, "highpass=f=120"],
  key2: [0.05, `0.3*${noise}*exp(-200*t)+0.3*sin(2*PI*150*t)*exp(-60*t)`, "highpass=f=120"],
  key3: [0.05, `0.35*${noise}*exp(-150*t)+0.25*sin(2*PI*190*t)*exp(-80*t)`, "highpass=f=120"],
  // A big number lands: a soft low thump whose pitch falls from about 120 Hz to 50 Hz.
  hit: [0.6, `0.8*sin(2*PI*(50*t+3.5*(1-exp(-20*t))))*exp(-6*t)+0.15*${noise}*exp(-200*t)`, "lowpass=f=3000"],
  // Passed or running: two rising tones.
  confirm: [0.45, "0.3*sin(2*PI*880*t)*exp(-30*t)+0.3*sin(2*PI*1320*(t-0.09))*exp(-9*(t-0.09))*gte(t,0.09)"],
  // A check fails: two short low buzzes.
  error: [0.36, "0.25*(2*gt(sin(2*PI*110*t),0)-1)*lt(mod(t,0.17),0.11)*exp(-3*t)", "lowpass=f=1200"],
};

mkdirSync(OUT, { recursive: true });
for (const [name, [seconds, expr, filters]] of Object.entries(SOUNDS)) {
  // A 4 ms fade-in and a short fade-out remove clicks at the start and end of each sound.
  const fade = `afade=t=in:d=0.004,afade=t=out:st=${(seconds - 0.02).toFixed(3)}:d=0.02`;
  const chain = [filters, fade].filter(Boolean).join(",");
  const r = spawnSync(ffmpeg, ["-loglevel", "error", "-y", "-f", "lavfi", "-i", `aevalsrc='${expr}':s=${RATE}:d=${seconds}`, "-af", chain, "-ac", "1", join(OUT, `${name}.wav`)], { stdio: "inherit" });
  if (r.status !== 0) {
    console.error(`✗ could not make ${name}.wav`);
    process.exit(r.status ?? 1);
  }
}
console.log(`sound effects: ${Object.keys(SOUNDS).length} files in public/sfx`);
