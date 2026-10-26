# Blind schedule-checker rules (from BRIEF.md sections 10-11 and config/scheduler.toml, config/shop.toml only)

Sources: `S` = config/scheduler.toml, `SH` = config/shop.toml, `B10.n` / `B11.n` = BRIEF.md section 10 / 11 item n.

## Time model
- Integer minutes. Minute 0 = Monday 08:00 shop-local (S line 2). Day `d` (0 = Monday) starts at minute `1440*d - 480` midnight-relative, so wall clock `HH:MM` on day `d` is minute `1440*d + (HH*60+MM) - 480`.
- Intervals are half-open `[start, end)`; `end` is exclusive. Two intervals overlap iff `a.start < b.end and b.start < a.end`.
- Shift windows (S `[shifts]`, SH `[[shifts]]`), for week `w` in {0,1}, `d = 7w + weekday-1`:
  - Mon-Fri 08:00-17:00 -> `[1440d, 1440d + 540)`. Week 0: Mon [0,540), Tue [1440,1980), Wed [2880,3420), Thu [4320,4860), Fri [5760,6300); week 1 adds 10080.
  - Sat 09:00-13:00 -> `[1440d + 60, 1440d + 300)`. Week 0: [7260,7500); week 1: [17340,17580).
  - Sunday: no shift.

## Durations (S `[durations]`, B10.2, B11.2: the checker recomputes them)
Let `q` = quantity, `mpp` = minutes_per_part, `ppp` = post_minutes_per_part, `cool` = cool_down_minutes[process] (fdm 20, resin 45, cnc 0).
- prep = `prep_minutes` = **15**
- machine = `setup_minutes + q*mpp + cool` = **15 + q*mpp + cool** (cool-down is inside the machine task: "part stays on the machine")
- post = **q*ppp**, present only when `ppp > 0`
- finish = `finish_base_minutes + finish_minutes_per_part*q` = **10 + q**
- changeover (30) is NOT part of the machine task; it is a required idle gap (rule B10).

## Rules
| ID | Rule | Source |
|---|---|---|
| B01 | Every instance job appears exactly once: either in `plan.jobs` or in `plan.unscheduled`, never both, never neither; no unknown or duplicate job ids. | B11.3 "check every rule"; S `unscheduled_job` weight implies unscheduled is an allowed outcome |
| B02 | A scheduled job names a machine that exists in the instance and has exactly one `prep`, one `machine`, one `finish` task, and one `post` task iff `post_minutes_per_part > 0` (zero post tasks otherwise). | B10.1 "each job becomes ordered tasks"; S durations |
| B03 | Every task has integer `0 <= start < end <= horizon`. | S `horizon_days = 14`; B10 plan is within the horizon (unscheduled_job = "does not fit the horizon") |
| B04 | Every task's `end - start` equals exactly its recomputed duration (above). | B11.2 "recomputes durations itself" |
| B05 | Tasks follow their order: `prep.end <= machine.start`, `machine.end <= post.start` (if post), `(post or machine).end <= finish.start`. Equality allowed. | B10.3 "Tasks follow their order" |
| B06 | The machine's `process` equals the job's `process`. | B10.3 "machine must ... support the material"; SH machines have a process |
| B07 | The job's `material` is in the machine's `materials` list. | B10.3, B11.3 "material compatible" |
| B08 | The part fits: `part_mm[i] <= build_mm[i]` for i = x, y, z (equal fits; no rotation). | B10.3 "machine must fit the part" |
| B09 | One task at a time per machine: no two machine tasks on the same machine overlap (half-open, so touching is fine). Cool-down counts as occupying the machine. | B10.3, B11.3 "No overlaps"; S cool_down comment |
| B10 | Changeover: if two consecutive machine tasks (by start time) on the same machine have different materials, `next.start >= prev.end + 30`. Same material: no gap needed. The first task on a machine needs no changeover. | S `changeover_minutes = 30 # extra, between consecutive jobs of different material on a machine` |
| B11 | Machine task start lies inside a shift: `shift.start <= start < shift.end`. It may run past the shift end, overnight, weekends. | S `[shifts]` "Machines may only START a task inside a shift but may run overnight" |
| B12 | Every manual task (prep, post, finish) lies entirely inside ONE shift: `shift.start <= start` and `end <= shift.end`. | S `[shifts]` "manual tasks must fit entirely inside one shift" |
| B13 | At every minute at most 2 manual tasks (all jobs, all kinds) run at once. | S `people_per_shift = 2` |
| B14 | No task of a job starts before the job's `arrival` (in practice `prep.start >= arrival`). | Order received; B10.1 work comes from orders |
| B15 | The machine task cannot start before the material is on hand: `machine.start >= release`. | B10.3 "cannot start before its materials arrive"; B11.3 "material ... available" |
| B16 | Fixed tasks unchanged: for each `fixed` entry, the job is scheduled (not unscheduled), its machine task is on `fixed.machine` and starts exactly at `fixed.start` (its duration is still checked by B04). | B10.3 "Finished and running tasks are fixed"; B11.3 "finished tasks unchanged" |
| B17 | Deadlines are reported, not violations: a late job does not make a plan invalid. | B11.3 "lateness is reported, not hidden" |

## Metrics (B10.7, B11.4; recomputed by the checker, scheduled jobs only)
- `completion(j)` = end of `j`'s finish task.
- `late_jobs` = count of jobs with `completion > due` (`completion == due` is on time).
- `total_lateness_minutes` = sum of `max(0, completion - due)`.
- `changeovers` = per machine, machine tasks sorted by start, count consecutive pairs whose materials differ.
- `finish_time` = max completion over scheduled jobs (0 if none).
- `unscheduled` = length of `plan.unscheduled`.
- `machine_utilisation` (not used in cases) = sum of machine-task minutes on a machine / horizon.
- `objective` (S `[weights]`) = sum over late jobs of `5000*m` + sum of `10*lateness*m` (m = 3 if rush else 1) + `600*changeovers` + `1*finish_time` + `1000000*unscheduled`.

## Ambiguities and chosen interpretation
1. **Changeover: gap or longer task?** "extra, between consecutive jobs" could mean the machine task is 30 min longer. Chosen: a required idle gap before the next machine task, because the task duration should be a property of the job alone. The gap may fall outside a shift (only the machine start must be in a shift).
2. **Changeover with no predecessor.** Initial loaded material is unknown; the first task on a machine needs no changeover and is not counted.
3. **Rotation for fit.** Brief says "fit the part"; a solver could rotate. Chosen: no rotation (part_mm is taken as print orientation). Cases avoid depending on this.
4. **Which tasks need material (release).** Prep includes "load the machine", which could need material. Chosen: only the machine task is gated by `release`. A release case necessarily has prep before release; a checker that gates prep too would report an extra violation there.
5. **Arrival vs release.** Arrival gates all tasks (order not yet received); release gates machine only.
6. **Due time = finish end.** "due: minute the job should be finished (packed)". `completion == due` is on time.
7. **Durations exact vs minimum.** Chosen: exact. A longer task would hide idle time and break metrics.
8. **Prep uses the machine?** "slice, load the machine" sounds like it touches the machine. Chosen: prep is purely manual and does not occupy the machine (S lists it as its own task with staff).
9. **DST.** Minute 0 is shop-local Monday 08:00; if the horizon crosses a DST change, wall clock and elapsed minutes differ by 60. Chosen: minutes are wall-clock offsets (every day is 1440 minutes).
10. **Fixed tasks and other rules.** A running task may have started outside today's shift, before release, or before minute 0. Chosen: a fixed machine task must still match B16 and B04; cases keep fixed tasks otherwise valid, so this does not matter for them. Whether a fixed task is exempt from B11/B15 is open.
11. **Fixed job's prep.** Already done in reality, but the plan format still lists it; chosen: it must still be present and valid.
12. **Staff vs shift.** `people_per_shift = 2` is per shift; with shifts never overlapping, this equals "at most 2 concurrent manual tasks".
13. **Post longer than a shift** (e.g. > 540 min) cannot be placed; such a job must be unscheduled. Not split across shifts.
14. **Unscheduled feasible jobs** are allowed (penalised, not invalid).
15. **Rush has no hard effect.** "rush jobs first" is a weighted goal only.
16. **Horizon applies to all tasks**, including a machine task running overnight and the finish.
17. **Brief lists idle time, overtime and re-plan churn as goals** but S has no weights for them; they are not in the objective here.
18. **Overlap violations are pairwise**; cases report them with `job: null` since either job could be "the" offender.
