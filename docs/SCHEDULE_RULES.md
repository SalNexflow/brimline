# Schedule rules

The rules a plan must obey, written as a spec for the independent checker (M4). The scheduler,
the baselines and the checker all follow this page; the checker reimplements it without
importing any scheduler code. Sources: `docs/BRIEF.md` sections 10 and 11, `config/scheduler.toml`,
`config/shop.toml`, and decisions D53, D54.

## Time

- Whole minutes. Minute 0 is Monday 08:00 shop time (Europe/Berlin). An interval `[start, end)`
  includes `start` and excludes `end`, so a task 0-100 and a task 100-200 do not overlap.
- **Shift windows** come from `[shifts]`: for each day `d` in `0 .. horizon_days-1`, the
  weekday is `d mod 7 + 1` (1 = Monday); if it has hours `[from, to]`, the window is
  `[d*1440 - 480 + from, d*1440 - 480 + to)` with `from`, `to` in minutes after midnight.
  With today's config: Mon-Fri 0-540, 1440-1980, ...; Saturday 7260-7500; no Sunday.
- **Horizon** = `horizon_days * 1440` minutes.

## Tasks of a job

| Kind | Who | Duration (minutes) |
|---|---|---|
| prep | one person | `prep_minutes` |
| machine | one machine | `setup_minutes + quantity * minutes_per_part + cool_down_minutes[process]` (0 if the process is missing) |
| post | one person | `quantity * post_minutes_per_part` |
| finish | one person | `finish_base_minutes + quantity * finish_minutes_per_part` |

A task whose duration is 0 does not exist. A job with a **fixed** machine task has no prep
(it is already done), and when the fixed task has an `end` (from real clock times: when it
ended, or for a running task the later of its planned end and now), it lasts `end - start`
instead of the formula.

Job fields that are easy to misread: `arrival` is the **order** in which jobs came in (FCFS
sorts by it), not a minute, so no rule compares it with a time. `release` is the minute the
material is on hand. `due` is the minute by which the job should be packed.

## Material stock (optional, M9)

An instance may state how much of each material there is and when more arrives. Without a
`stock` section there is no stock rule (older documents and the benchmark instances).

- `stock`: grams of each material available to the work in this plan at `plan_start`, a map
  from material code to a whole number `>= 0`. A material that is not listed has 0 grams.
  Prints already running or done (fixed machine tasks) took their material before this number
  was stated, so they use nothing here.
- `deliveries`: a list of `{material, at, grams}`: `grams` (`>= 1`) of `material` arrive at
  minute `at`. A delivery at minute `t` can be used by a machine task starting at `t`.
- `grams_per_part` on each job (`>= 1`): a job uses `quantity * grams_per_part` grams of its
  material, all of it at the **start of its machine task**.

The **level** of a material at minute `t` is its `stock`, plus the grams of its deliveries with
`at <= t`, minus the grams used by every planned job that has no fixed task and whose machine
task starts at or before `t`. Unscheduled jobs use nothing.

## Rules

Each rule has a code the checker reports.

| Code | Rule |
|---|---|
| R01 `unknown_job` | Every job in the plan (planned or unscheduled) exists in the instance. |
| R02 `duplicate_job` | A job appears at most once across planned and unscheduled. |
| R03 `missing_job` | Every job of the instance appears: planned or listed as unscheduled. Nothing is silently dropped. |
| R04 `unknown_machine` | The plan's machine exists. |
| R05 `wrong_tasks` | A planned job has exactly its existing tasks (see above), each once, listed in the order prep, machine, post, finish. |
| R06 `wrong_duration` | Each task's `end - start` equals its duration. |
| R07 `task_order` | A task starts no earlier than the previous task of the same job ends. |
| R08 `not_eligible` | The machine's process equals the job's process, the job's material is in the machine's materials, and the part fits: both size triples sorted, each part side <= the build side (the part may be turned). |
| R09 `before_release` | The machine task starts no earlier than the job's `release` (material on hand). |
| R10 `machine_off_shift` | A machine task starts inside a shift window: `from <= start < to`. It may run past the shift. |
| R11 `manual_off_shift` | A manual task lies entirely inside one shift window: `from <= start` and `end <= to`. |
| R12 `staff_overload` | At no minute do more than `people_per_shift` manual tasks run. |
| R13 `machine_overlap` | On one machine, no two machine tasks overlap. This includes fixed tasks of jobs listed as unscheduled: a fixed task always blocks its machine. |
| R14 `changeover` | On one machine, sorted by start, two neighbouring machine tasks of different material are at least `changeover_minutes` apart (gap = next start - previous end). Not required when both are fixed. |
| R15 `fixed_moved` | A planned job with a fixed task keeps its machine and its machine start exactly. |
| R16 `past_horizon` | Every task ends at or before the horizon, except a fixed machine task (it is a fact). |
| R18 `before_plan_start` | No task starts before `plan_start`, the moment of planning (0 when the document does not say), except a fixed machine task. You cannot plan work into the past. |
| R19 `machine_down` | No task runs on a machine during one of its downtimes (`[start, end)`; touching is fine). A downtime needs no changeover before or after it. A fixed task inside a downtime is an impossible instance (R17): a print lost to a breakdown must not be fixed. |
| R20 `material_short` | When the instance has `stock`: the level of every material is `>= 0` at every minute. Each planned job without a fixed task whose machine task starts at a minute when its material's level is below 0 is reported: it would start before the material it needs is there. (The level only falls when a machine task starts, so these are the only minutes to check.) |
| R17 `bad_instance` | The instance itself is impossible or does not match the config: a fixed task for an unknown job or machine, two fixed tasks overlapping on a machine, a job with quantity or minutes_per_part below 1, a negative post time, a part side below 1 mm, two jobs or machines with the same id, a horizon below 1, a fixed task whose end is not after its start, a downtime on an unknown machine or ending before it starts, a fixed task inside a downtime, shifts or staff in the document that differ from `config/scheduler.toml`, a negative `stock`, `deliveries` without `stock`, a delivery of fewer than 1 gram, a `grams_per_part` below 1, or (when there is `stock`) a job without a fixed task that has no `grams_per_part`. The plan is not judged further. |

Fixed machine tasks are facts: R08, R09, R10, R16, R18 and R20 do not apply to them. A job with a fixed
task may still be listed as unscheduled (when its later tasks cannot fit); its fixed task then
keeps blocking the machine (R13), the job counts in "late or unscheduled", and the checker
warns if it looks like it could have fitted (below).

## Deadlines (reported, not violations)

For each planned job: completion = the latest end of its tasks (the finish task in a valid plan); tardiness = `max(0, completion - due)`;
late if tardiness > 0. Rush jobs are listed. Lateness is never hidden: unscheduled jobs are
counted in "late or unscheduled".

## Suspicious unscheduled jobs (a warning, not a violation)

A plan may leave a job unscheduled, and proving that it could not fit is the scheduler's job,
not the checker's. But the checker flags an unscheduled job as **suspicious** when a simple
witness exists that it might have fitted:

- its material is on hand before the horizon (`release` < horizon), and
- some eligible machine has a free stretch, starting at or after the release and inside a shift,
  and (when there is `stock`) at or after the first minute from which the material's level,
  with the plan's own use, never falls below the job's grams again,
  long enough for the machine task, keeping `changeover_minutes` from any task of a different
  material on that machine (planned or fixed), ending by the horizon, and
- its post-processing and finishing then fit in shifts before the horizon.

It ignores staff and manual tasks, so it can raise a false warning; it is a pointer for a human,
never a verdict.

## Metrics

Computed from the plan and the instance only.

| Metric | Definition |
|---|---|
| scheduled | planned jobs |
| unscheduled | jobs listed as unscheduled |
| late_jobs | planned jobs with tardiness > 0 |
| late_or_unscheduled | late_jobs + unscheduled |
| rush_late_jobs | late planned jobs that are rush |
| total_lateness_minutes | sum of tardiness over planned jobs |
| changeovers | on each machine, the machine tasks sorted by start (planned jobs, plus the fixed task of any job left unscheduled); neighbours with different material count 1, except two fixed tasks (no changeover was needed between them) |
| finish_time | latest completion of a planned job (0 if none) |
| utilisation | planned machine-task minutes from minute 0 on (a fixed task running since before minute 0 counts only its part after it) / (number of machines * finish_time); 0 if finish_time is 0 |
| objective | sum over planned jobs of `m * (late_job * [late] + tardiness_per_minute * tardiness)`, where `m = rush_multiplier` for rush jobs else 1; plus `changeover * changeovers + finish_time_per_minute * finish_time + unscheduled_job * unscheduled` |

## Differences found by the blind review (M4)

Before the checker was written, a fresh-context reviewer who saw only `docs/BRIEF.md` and
`config/` wrote its own rules (`docs/checker_blind_rules.md`) and 27 cases
(`services/engine/tests/checker_blind_cases.json`, kept as written). 24 cases agreed with this
page. The differences and how each was resolved (decisions D57 to D61):

| Topic | Reviewer | This page | Resolution |
|---|---|---|---|
| `arrival` | a minute; no task before it | the order jobs came in | Kept ours; the field is now described above (D57). |
| Prep of a fixed job | must be in the plan | not in the plan | Kept ours: it happened in the past, maybe last week, so no shift could hold it (D58). |
| Fixed job left unscheduled | a violation | allowed, still blocks, warned as suspicious | Kept ours: otherwise a fixed task near the end of the horizon makes every plan invalid (D59). |
| Turning a part to fit | not allowed | allowed | Kept ours (printers and mills can orient a part); the reviewer's cases do not depend on it (D60). |
| Utilisation | per machine, over the horizon | all machines, over the finish time | Kept ours, so the bench numbers stay comparable; both are stated (also D60). |
| Fixed tasks and shift/release rules | open question | exempt (facts) | Kept ours (D61). |
