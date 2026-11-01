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
const costing = read("costing.json");
const shortage = read("shortage.json");

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
const flagCell = (bias, n) => costing.held_out.find((r) => r.bias === bias && r.jobs_per_type === n);
const flagRate = (bias, n, field = "detected") => pct(flagCell(bias, n)[field] / flagCell(bias, n).runs);
const sizes = [...new Set(costing.held_out.map((r) => r.jobs_per_type))].sort((a, b) => a - b);
const biases = [...new Set(costing.held_out.map((r) => r.bias))].sort((a, b) => a - b);
const slips = [...new Set(shortage.rows.map((r) => r.slip_days))].sort((a, b) => a - b);
const atSlip = (days, key, field = "late_or_unscheduled") =>
  mean(shortage.rows.filter((r) => r.slip_days === days).map((r) => r[key][field]));
const worstSlip = slips.at(-1);
const stockPlans = shortage.rows.flatMap((r) => [r.edd, r.cpsat, r.cpsat_with_suggestions]);
const stockMutations = Object.values(shortage.stock_mutations);
const stockApplied = stockMutations.reduce((s, [a]) => s + a, 0);
const stockCaught = stockMutations.reduce((s, [, c]) => s + c, 0);

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
| Re-planning | Re-plans that pass the independent checker | ${frac(replanValid, replan.rows.length)} | \`make replan-bench\` |
| Quoted vs actual (code) | Under-quoted type flagged: true bias 1.40, ${sizes.at(-1)} jobs/type | ${flagRate(1.4, sizes.at(-1))} of ${flagCell(1.4, sizes.at(-1)).runs} runs | \`make eval\` |
| Quoted vs actual (code) | Flagged at 1.10 (under the 15 % threshold), any sample size | ${sizes.reduce((sum, n) => sum + flagCell(1.1, n).detected, 0)} runs of ${sizes.reduce((sum, n) => sum + flagCell(1.1, n).runs, 0)} | \`make eval\` |
| Quoted vs actual (code) | Control false alarms per run, all job types together, worst sample size | ${pct(Math.max(...sizes.map((n) => flagCell(1.0, n).false_alarm_runs / flagCell(1.0, n).runs)))} | \`make eval\` |
| Shortage planning (code) | Late or unscheduled jobs after a ${worstSlip}-day delivery slip: CP-SAT / with the suggested orders | ${one(atSlip(worstSlip, "cpsat"))} / ${one(atSlip(worstSlip, "cpsat_with_suggestions"))} | \`make shortage-bench\` |
| Shortage planning (code) | Plans checker-valid, stock rule included / corrupted stock records caught | ${frac(stockPlans.filter((p) => p.valid).length, stockPlans.length)} / ${frac(stockCaught, stockApplied)} | \`make shortage-bench\` |`;

const flagTable = `Runs that flag the under-quoted material (TPU-BLACK), ${flagCell(1.0, sizes[0]).runs} held-out synthetic histories per cell, ${costing.types} materials each (\`make eval\`, rule in \`config/costing.toml\`):

| True bias | ${sizes.map((n) => `${n} jobs/type`).join(" | ")} |
|---${"|---".repeat(sizes.length)}|
${biases.map((b) => `| ${b.toFixed(2)}${b === 1 ? " (control)" : ""} | ${sizes.map((n) => flagRate(b, n)).join(" | ")} |`).join("\n")}

Control false alarms per run, across all ${costing.types} materials together: ${sizes.map((n) => `${flagRate(1.0, n, "false_alarm_runs")} at ${n}`).join(", ")}. Seeded demo history: flags ${costing.seeded.biased.join(", ") || "nothing"}; the same history without the bias: flags ${costing.seeded.control.join(", ") || "nothing"}.`;

const claims = `- Built an **independent plan checker** that shares no code with the scheduler and caught **${frac(caught, applied)}** deliberately corrupted plans across ${mutations.length} kinds of error (\`make bench\`).
- Scheduled with **OR-Tools CP-SAT**: on 80-job instances, **${one(late(80, "cpsat-simple"))}** late or unscheduled jobs on average against **${one(late(80, "edd"))}** for earliest-due-date (\`make bench\`).
- Made re-planning stable: after a machine breakdown the re-plan moves **${one(moved("machine_down", "configured"))}** of ${one(movable("machine_down"))} jobs instead of **${one(moved("machine_down", "none, approved hint"))}** without stability costs, with all **${frac(replanValid, replan.rows.length)}** re-plans checker-valid (\`make replan-bench\`).
- Kept the LLM out of decisions: natural-language search turns a question into a typed filter (never SQL) with **${frac(search.correct, search.n)}** exactly right on a blind held-out set and **${frac(search.widening_blocked, search.widening_attacks)}** access-widening attacks blocked (\`make eval\`).
- Evaluated every AI step blind, with dev and held-out sets written by a fresh agent: the disruption reader is exactly right on **${pct(disruption.all_correct)}** of held-out messages with **${disruption.unsafe_cancellations}** unsafe cancellations (\`make eval\`).
- Made material a hard constraint: stock and deliveries go into CP-SAT as a reservoir and an independent checker rule; after a ${worstSlip}-day delivery slip, following the code's purchase suggestions cut late or unscheduled jobs from **${one(atSlip(worstSlip, "cpsat"))}** to **${one(atSlip(worstSlip, "cpsat_with_suggestions"))}** on average, with **${frac(stockPlans.filter((p) => p.valid).length, stockPlans.length)}** plans passing the checker, stock rule included (\`make shortage-bench\`).
- Closed the quote-versus-actual loop with a code-only under-quote flag (a sign test against a 15 % threshold): on held-out synthetic histories it flags a material quoted 40 % low in **${flagRate(1.4, 10)}** of runs at 10 jobs per material and **${flagRate(1.4, sizes.at(-1))}** at ${sizes.at(-1)}, flags a 10 % under-quote in **${sizes.reduce((sum, n) => sum + flagCell(1.1, n).detected, 0)}** of ${sizes.reduce((sum, n) => sum + flagCell(1.1, n).runs, 0)} runs and raises **${pct(Math.max(...sizes.map((n) => flagCell(1.0, n).false_alarm_runs / flagCell(1.0, n).runs)))}** false alarms per run; its weak spot is a 20 % under-quote, caught in only **${flagRate(1.2, sizes.at(-1))}** of runs even at ${sizes.at(-1)} jobs (\`make eval\`).`;

const shortageTable = `${shortage.seeds.length} seeded ${shortage.jobs}-job instances, ${Math.round(shortage.cover * 100)} % of each material on hand and one delivery with the rest; that delivery slips by the days shown (\`make shortage-bench\`, means over seeds):

| Delivery slip | Late or unscheduled: no material limit | EDD | CP-SAT | CP-SAT with the suggested orders | Hours late: CP-SAT / with orders |
|---|---|---|---|---|---|
${slips.map((d) => `| ${d} d | ${one(atSlip(d, "unlimited"))} | ${one(atSlip(d, "edd"))} | ${one(atSlip(d, "cpsat"))} | ${one(atSlip(d, "cpsat_with_suggestions"))} | ${one(atSlip(d, "cpsat", "lateness_minutes") / 60)} / ${one(atSlip(d, "cpsat_with_suggestions", "lateness_minutes") / 60)} |`).join("\n")}

Every plan passes the independent checker, its stock rule included (${frac(stockPlans.filter((p) => p.valid).length, stockPlans.length)}), and it catches ${frac(stockCaught, stockApplied)} deliberately corrupted stock records (stock reduced, a delivery removed, a delivery one minute late). Suggested orders are placed at the moment of planning; ${shortage.rows.flatMap((r) => r.suggested_orders).filter((o) => o.in_time).length} of ${shortage.rows.flatMap((r) => r.suggested_orders).length} could arrive before the first short need.`;

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
const next = fill(fill(fill(fill(current, "results", results), "claims", claims), "costing", flagTable), "shortage", shortageTable);
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
