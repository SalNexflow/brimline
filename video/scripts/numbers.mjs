// Every number the video shows, read from the result files (storyboard: number register N1 to N12).
// Run before the studio and every render; it fails, and so stops the render, if a file or field is
// missing or a stated condition does not hold. Writes src/numbers.generated.json (git-ignored).
import { readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const RESULTS = join(HERE, "..", "..", "eval", "results");

function read(name) {
  return JSON.parse(readFileSync(join(RESULTS, name), "utf-8"));
}

function need(value, what) {
  if (value === undefined || value === null || Number.isNaN(value)) throw new Error(`missing: ${what}`);
  return value;
}

const mean = (xs) => xs.reduce((a, b) => a + b, 0) / xs.length;
const round1 = (x) => Math.round(x * 10) / 10;

// N1 to N3: quote extraction, held-out set.
const quote = read("quote_extract_deepseek-flash.json");
const held = need(quote.summary?.heldout, "quote summary.heldout");

// N4: the independent checker's mutation test.
const bench = read("bench.json");
const mutations = Object.values(need(bench.checker?.mutations, "bench checker.mutations"));

// N5 to N7: re-plan after FDM-1 goes down, configured costs against the fair baseline.
const replan = read("replan.json");
const rows = (costs) => replan.rows.filter((r) => r.scenario === "machine_down" && r.costs === costs);
const configured = rows("configured");
const baseline = rows("none, approved hint");
if (configured.length === 0 || configured.length !== baseline.length) throw new Error("re-plan rows missing");
for (const c of configured) {
  const b = baseline.find((x) => x.seed === c.seed);
  if (!b || b.lateness_minutes !== c.lateness_minutes || b.late_or_unscheduled !== c.late_or_unscheduled) {
    throw new Error(`"same lateness" does not hold for seed ${c.seed}`);
  }
}

// N8 to N10: the dispatch agent and guard, dev and held-out together.
const dispatch = read("dispatch_deepseek-flash.json");
const both = (key) => need(dispatch.summary?.dev?.[key], `dispatch dev.${key}`) + need(dispatch.summary?.heldout?.[key], `dispatch heldout.${key}`);

// N11, N12: the scheduler against earliest-due-date.
const main = need(bench.main, "bench main");
const lateAt80 = (method) => round1(mean(main.filter((r) => r.jobs === 80 && r.method === method).map((r) => r.late_or_unscheduled)));
const instances = [...new Set(main.map((r) => r.instance))];
const objective = (instance, method) => need(main.find((r) => r.instance === instance && r.method === method)?.objective, `${instance} ${method}`);

const numbers = {
  quote: {
    allRightPercent: Math.round(need(held.all_correct, "all_correct") * 100), // N1
    messages: need(held.items, "items"), // N2
    harmfulErrors: need(held.harmful_errors, "harmful_errors"), // N3
    source: `held-out eval, ${quote.model}, ${quote.generated_at.slice(0, 10)}`,
  },
  checker: {
    caught: mutations.reduce((n, m) => n + m.caught, 0), // N4
    applied: mutations.reduce((n, m) => n + m.applied, 0),
    kinds: mutations.filter((m) => m.applied > 0).length,
    source: `scheduler benchmark, ${bench.generated_at.slice(0, 10)}`,
  },
  replan: {
    movedConfigured: round1(mean(configured.map((r) => r.jobs_moved))), // N5
    movedBaseline: round1(mean(baseline.map((r) => r.jobs_moved))), // N6
    latenessHours: round1(mean(configured.map((r) => r.lateness_minutes)) / 60), // N7, equal per seed
    source: `${replan.n_jobs}-job benchmark, FDM-1 down; baseline: re-solved from the approved plan without re-planning costs`,
  },
  dispatch: {
    unsafeThrough: both("unsafe_through"), // N8
    unsafeCalls: both("unsafe_calls"), // N9
    withoutProceed: both("executed_without_proceed"), // N10
    source: `${both("scenarios")} blind scenarios, ${dispatch.model}, simulated machines`,
  },
  scheduler: {
    lateEdd: lateAt80("edd"), // N11
    lateOurs: lateAt80("cpsat-simple"),
    better: instances.filter((i) => objective(i, "cpsat-simple") < objective(i, "edd")).length, // N12
    instances: instances.length,
    source: `lower weighted cost than earliest-due-date, seeded ${Math.min(...need(bench.sizes, "bench sizes"))} to ${Math.max(...bench.sizes)}-job plans`,
    lateSource: `seeded 80-job plans, ${need(bench.seeds, "bench seeds").length} seeds, ${bench.generated_at.slice(0, 10)}`,
  },
};

writeFileSync(join(HERE, "..", "src", "numbers.generated.json"), JSON.stringify(numbers, null, 2) + "\n");
console.log(JSON.stringify(numbers));
