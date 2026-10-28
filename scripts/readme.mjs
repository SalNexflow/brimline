#!/usr/bin/env node
// Writes the README's results tables and resume claims from the files `make eval`, `make bench`
// and `make replan-bench` produce (M11, hard rule 11: no number in the README is typed by hand).
//
//   node scripts/readme.mjs           rewrite the generated blocks in README.md
//   node scripts/readme.mjs --check   fail if README.md differs from what the results say (gate)
import { readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const RESULTS = join(ROOT, "eval", "results");
const README = join(ROOT, "README.md");
const read = (name) => JSON.parse(readFileSync(join(RESULTS, name), "utf8"));

const pct = (x) => `${Math.round(x * 100)} %`;
const frac = (a, b) => `${a}/${b}`;
const mean = (xs) => xs.reduce((s, x) => s + x, 0) / xs.length;
const one = (x) => (Math.round(x * 10) / 10).toFixed(1);

// --- The numbers, each from one results file ---------------------------------------------------

const quote = read("quote_extract_deepseek-flash.json").summary.heldout;
const disruption = read("disruptions_deepseek-flash.json").summary.heldout;
const search = read("search_deepseek-flash.json").summary.held_out;
const files = read("files.json").scores["held out (blind)"];
const bench = read("bench.json");
const replan = read("replan.json");

const bySize = (jobs, method) => bench.main.filter((r) => r.jobs === jobs && r.method === method);
const late = (jobs, method) => mean(bySize(jobs, method).map((r) => r.late_or_unscheduled));
const lateHours = (jobs, method) => mean(bySize(jobs, method).map((r) => r.total_lateness_minutes)) / 60;
// Kinds that applied to these plans (a kind needing fixed tasks cannot, see BENCH.md).
const mutations = Object.values(bench.checker.mutations).filter((m) => m.applied > 0);
const applied = mutations.reduce((s, m) => s + m.applied, 0);
const caught = mutations.reduce((s, m) => s + m.caught, 0);
const moved = (scenario, costs) =>
  mean(replan.rows.filter((r) => r.scenario === scenario && r.costs === costs).map((r) => r.jobs_moved));
const movable = (scenario) => mean(replan.rows.filter((r) => r.scenario === scenario).map((r) => r.jobs_movable));
const replanValid = replan.rows.filter((r) => r.valid).length;

const results = `| Area | Measure (held-out set where there is one) | Result | Command |
|---|---|---|---|
| Quote reading (AI) | Messages with every field right | ${pct(quote.all_correct)} of ${quote.items} | \`make eval\` |
| Quote reading (AI) | Harmful errors (a wrong value that would reach a price) | ${quote.harmful_errors} | \`make eval\` |
| Disruption reading (AI) | Messages read exactly right | ${pct(disruption.all_correct)} of ${disruption.items} | \`make eval\` |
| Disruption reading (AI) | Cancellations the label does not have | ${disruption.unsafe_cancellations} | \`make eval\` |
| Search (AI) | Filter exactly right after code reads it | ${frac(search.correct, search.n)} | \`make eval\` |
| Search (AI) | Access-widening attacks blocked | ${frac(search.widening_blocked, search.widening_attacks)} | \`make eval\` |
| Search (AI) | Customer questions showing another customer's name | ${frac(search.leaking, search.customer_questions)} | \`make eval\` |
| File checker (code) | Broken files passed (false pass) | ${frac(files.false_pass, files.broken)} | \`make eval\` |
| File checker (code) | Overall verdict agrees with the label | ${frac(files.overall_agreement, files.n)} | \`make eval\` |
| Scheduler, 80 jobs | Late or unscheduled jobs: CP-SAT / EDD / first-come | ${one(late(80, "cpsat-simple"))} / ${one(late(80, "edd"))} / ${one(late(80, "fcfs"))} | \`make bench\` |
| Scheduler, 80 jobs | Total lateness, hours: CP-SAT / EDD | ${one(lateHours(80, "cpsat-simple"))} / ${one(lateHours(80, "edd"))} | \`make bench\` |
| Independent checker | Corrupted plans caught | ${frac(caught, applied)} (${mutations.length} kinds) | \`make bench\` |
| Independent checker | Plans checked valid / disagreements with the scheduler | ${frac(bench.checker.plans_valid, bench.checker.plans_checked)} / ${bench.checker.metric_disagreements.length} | \`make bench\` |
| Re-planning | Jobs moved after a breakdown: stability costs / none, same hint | ${one(moved("machine_down", "configured"))} / ${one(moved("machine_down", "none, approved hint"))} of ${one(movable("machine_down"))} | \`make replan-bench\` |
| Re-planning | Re-plans that pass the independent checker | ${frac(replanValid, replan.rows.length)} | \`make replan-bench\` |`;

const claims = `- Built an **independent plan checker** that shares no code with the scheduler and caught **${frac(caught, applied)}** deliberately corrupted plans across ${mutations.length} kinds of error (\`make bench\`).
- Scheduled with **OR-Tools CP-SAT**: on 80-job instances, **${one(late(80, "cpsat-simple"))}** late or unscheduled jobs on average against **${one(late(80, "edd"))}** for earliest-due-date (\`make bench\`).
- Made re-planning stable: after a machine breakdown the re-plan moves **${one(moved("machine_down", "configured"))}** of ${one(movable("machine_down"))} jobs instead of **${one(moved("machine_down", "none, approved hint"))}** without stability costs, with all **${frac(replanValid, replan.rows.length)}** re-plans checker-valid (\`make replan-bench\`).
- Kept the LLM out of decisions: natural-language search turns a question into a typed filter (never SQL) with **${frac(search.correct, search.n)}** exactly right on a blind held-out set and **${frac(search.widening_blocked, search.widening_attacks)}** access-widening attacks blocked (\`make eval\`).
- Evaluated every AI step blind, with dev and held-out sets written by a fresh agent: the disruption reader is exactly right on **${pct(disruption.all_correct)}** of held-out messages with **${disruption.unsafe_cancellations}** unsafe cancellations (\`make eval\`).`;

// --- Write or check -----------------------------------------------------------------------------

function fill(text, name, body) {
  const start = `<!-- generated:${name}:start (scripts/readme.mjs; do not edit by hand) -->`;
  const end = `<!-- generated:${name}:end -->`;
  const i = text.indexOf(start);
  const j = text.indexOf(end);
  if (i < 0 || j < 0) throw new Error(`README.md has no ${name} block`);
  return text.slice(0, i + start.length) + "\n" + body + "\n" + text.slice(j);
}

const current = readFileSync(README, "utf8");
const next = fill(fill(current, "results", results), "claims", claims);
if (process.argv.includes("--check")) {
  if (next !== current) {
    console.error("✗ README.md does not match eval/results (run `make readme` and commit it)");
    process.exit(1);
  }
  console.log("README.md matches eval/results");
} else {
  writeFileSync(README, next);
  console.log(next === current ? "README.md already up to date" : "README.md updated from eval/results");
}
