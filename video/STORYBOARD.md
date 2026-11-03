# Brimline product video: storyboard (draft for approval)

77.4 s, 1920 x 1080, 30 fps, captions only, sound effects on the animations (no music). Built in
Remotion. Craft rules: `.claude/skills/motion-video/SKILL.md`.

- **Beat grid:** cuts sit on a 0.6 s grid (100 BPM: a beat is 0.6 s, a bar 2.4 s); every shot
  starts on a beat. There is no music, so the grid now only keeps the rhythm of the cuts even.
- **Reading time:** every caption is on screen for at least `0.5 s + words / 3`; the hold column
  shows that this is met.
- **Numbers:** each is read from its result file when the video renders (register below), never
  typed. A small source line sits under every number ("held-out eval, deepseek-flash, 26 Oct").
- **Screens:** the real app in the approved soft-glass look, captured from the showcase stack
  (fictional shop, fake data, demo clock Monday 10:00). Machines are simulated and the video says so.

## Shots

| # | Time | Recipe | Visual (screen) | On-screen words | Hold check | Numbers | Out |
|---|---|---|---|---|---|---|---|
| 1 | 0.0 to 4.8 | Abstract data field | Thin lines (orders) drift and converge onto six lanes labelled with the shop's machine codes (FDM-1 to CNC-1); shallow depth of field, slow drift | "A made-to-order print and CNC shop." | 7 words, 2.8 s needed, 3.6 s shown | none | hard cut |
| 2 | 4.8 to 8.4 | Kinetic words | Words on the off-white page, a pastel bloom behind | "Plan it." / "Check it." / "Run it." (one after another) | 6 words, 2.5 s, 3.0 s | none | hard cut |
| 3 | 8.4 to 13.2 | Tilted panel stack | Orders list, Materials (the "! short" card), Queues: three real screens rising in depth | "Orders, machines, materials, people." | 4 words, 1.8 s, 3.6 s | none (UI counts are demo data) | blur dissolve |
| 4 | 13.2 to 14.4 | Word card | Logo mark and name | "Brimline" + small "fictional shop · fake data" | 5 words, 2.2 s; **runs into shot 5's first 1.0 s** | none | push-through |
| 5 | 14.4 to 19.2 | Macro UI crop | Quote review: the customer's message types in, then the extracted fields appear as chips with their "from message" source badges | "AI reads the customer's message." | 5 words, 2.2 s, 3.6 s | none | hard cut |
| 6 | 19.2 to 24.0 | Boundary (state change) | The frame splits: left "AI: words into data", right "Code: prices, dates, permissions", a line between; the quote's price lands on the code side | "Code computes every price, date and permission." | 7 words, 2.8 s, 3.6 s | none | hard cut |
| 7 | 24.0 to 29.4 | Number reveal | Number on a calm field, source line below | "85 %" + "every field right on 20 unseen messages", then "0" + "harmful errors" | 9 + 2 words, 3.5 s + 1.2 s, 4.8 s | N1, N2, N3 | blur dissolve |
| 8 | 29.4 to 34.2 | Floating window, zoom to region | Board: camera eases onto the "Independent check: passed" badge and the stat cards | "A second program checks every plan." | 6 words, 2.5 s, 3.6 s | none | hard cut |
| 9 | 34.2 to 37.8 | State change (illustration) | Abstract plan bars; one bar slides into another's time; the badge flips to "✗ machine_overlap". Labelled "planted error" | "It shares no code with the scheduler." | 7 words, 2.8 s, 3.0 s | none | match cut |
| 10 | 37.8 to 41.4 | Number reveal | The two halves of the number settle | "2,880 / 2,880" + "planted rule breaks caught" | 4 words, 1.8 s, 3.0 s | N4 | blur dissolve |
| 11 | 41.4 to 46.2 | Macro UI crop | Board, "Something went wrong?": a planner types that FDM-1 is down; the events appear as chips to confirm | "A printer goes down." | 4 words, 1.8 s, 3.6 s | none | hard cut |
| 12 | 46.2 to 51.0 | State change | Draft plan with its changes: bars shift on the timeline, the check badge passes, the cursor presses "Approve plan" | "The plan moves. A person approves." | 6 words, 2.5 s, 3.6 s | none | hard cut |
| 13 | 51.0 to 54.6 | Number reveal | "3.7" settles beside a struck-through "14.3" | "jobs moved instead of 14.3, same lateness" + source line "40-job benchmark, FDM-1 down 4 h; baseline: re-solved from the approved plan without re-planning costs" | 7 words, 2.8 s, 3.0 s | N5, N6, N7 | blur dissolve |
| 14 | 54.6 to 59.4 | Floating window | Dispatch: the proposal card, the box ticked, "Proceed" pressed. Corner label "Simulated machines" | "An agent proposes. A person says go." | 7 words, 2.8 s, 3.6 s | none | hard cut |
| 15 | 59.4 to 63.0 | State change | The tool-call row fades in ("agent · start_task · allowed"); CNC-1's pill turns from "○ Idle" to "▶ Running" | "Code checks every call." | 4 words, 1.8 s, 3.0 s | none | hard cut |
| 16 | 63.0 to 66.6 | Number reveal | Two short lines on one card | "Unsafe calls passed: 0 of 10." / "Without Proceed: 0" | 9 words, 3.5 s, 3.6 s | N8, N9, N10 | blur dissolve |
| 17a | 66.6 to 70.2 | Number reveal | "38.4" settles, then "10.8" beside it | "80 jobs. Late: earliest-due-date 38.4, ours 10.8" (each part of "earliest-due-date" counted as a word) | 9 words, 3.5 s, 3.6 s | N11 | hard cut on the beat |
| 17b | 70.2 to 73.2 | Number reveal | "15 / 15" settles | "Better on 15 of 15 plans" + source line "lower weighted cost than earliest-due-date, seeded 20 to 80-job plans" | 6 words, 2.5 s, 3.0 s | N12 | hard cut |
| 18 | 73.2 to 77.4 | Typewriter + end card | Monospace caps type out, then the logo holds | "BRIMLINE" / "FICTIONAL SHOP · FAKE DATA · SIMULATED MACHINES" / "github.com/SalNexflow/brimline" | held 2.4 s | none | end |

Chapters: opening 0 to 14.4 s, AI versus code 14.4 to 29.4 s, the checker 29.4 to 41.4 s,
re-plan 41.4 to 54.6 s, dispatch 54.6 to 66.6 s, results 66.6 to 77.4 s.

## Number register (read at render time)

Values below are today's, computed from the files; the render reads them again and fails if a
file or field is missing.

| Id | On screen | Value now | File | Field and computation |
|---|---|---|---|---|
| N1 | "85 %" | 0.85 | `eval/results/quote_extract_deepseek-flash.json` | `summary.heldout.all_correct` x 100 |
| N2 | "20 unseen messages" | 20 | same | `summary.heldout.items` |
| N3 | "0 harmful errors" | 0 | same | `summary.heldout.harmful_errors` |
| N4 | "2,880 / 2,880" | 2880 / 2880 | `eval/results/bench.json` | sum of `checker.mutations[*].caught` / sum of `checker.mutations[*].applied` |
| N5 | "3.7" | 3.7 | `eval/results/replan.json` | mean `jobs_moved` of `rows` with `scenario == "machine_down"` and `costs == "configured"` |
| N6 | "14.3" | 14.3 | same | same, `costs == "none, approved hint"`: the M6 report's fair baseline (no re-planning costs, search started from the approved plan) |
| N7 | "same lateness" | identical per seed (2896, 0, 3631 min; mean 36.3 h) | same | `lateness_minutes` and `late_or_unscheduled` of the N5 and N6 rows, compared seed by seed; the render fails unless every pair is equal |
| N8 | "0" (got through) | 0 | `eval/results/dispatch_deepseek-flash.json` | `summary.dev.unsafe_through + summary.heldout.unsafe_through` |
| N9 | "of 10" | 10 | same | `summary.dev.unsafe_calls + summary.heldout.unsafe_calls` |
| N10 | "0 actions without a Proceed" | 0 | same | `summary.dev.executed_without_proceed + summary.heldout.executed_without_proceed` |
| N11 | "earliest-due-date 38.4, ours 10.8" | 38.4 / 10.8 | `eval/results/bench.json` | mean `late_or_unscheduled` of `main` rows with `jobs == 80`, `method == "edd"` (earliest-due-date) / `"cpsat-simple"` (Brimline's planner) |
| N12 | "15 of 15" | 15 / 15 | same | instances in `main` (5 seeds each at 20, 40, 80 jobs) where `cpsat-simple`'s `objective` is below `edd`'s / all instances |

Source lines under the numbers come from the same files: `generated_at`, `model` and the set
(held out, seeded benchmark), so each number says where it came from.

## Claim register (statements that are not numbers)

| Shot | Claim | Traced to |
|---|---|---|
| 5 | AI reads the customer's message | The quote-extraction eval above (N1 to N3); `make eval` |
| 6 | Code computes every price, date and permission | `uv run pytest tests/test_quote_extract.py::test_the_schema_has_no_price_discount_or_date_fields` (the model's schema has no price, discount or date field) and `tests/test_permissions.py::test_permission_table`; hard rules 1 and 4 |
| 8 | A second program checks every plan | `bench.json` `checker.plans_checked == plans_valid == 60` and `replan.json` 60 of 60 rows valid; the board re-checks the saved plan on every view (`CheckBadge`) |
| 9 | It shares no code with the scheduler | `uv run pytest tests/test_checker_independence.py` (source imports only the standard library and itself; running it loads no scheduler module) |
| 12 | A person approves | `tests/test_planning_api.py::test_only_a_planner_approves`, `::test_approval_is_audited_writes_tasks_and_replays` |
| 14 | A person says go | N10, and `tests/test_dispatch_api.py::test_calls_nobody_approved_are_refused_and_logged` |
| 15 | Code checks every call | N8 and N9, and `uv run pytest tests/test_dispatch_guard.py` |
| 18 | Fictional shop, fake data, simulated machines | CLAUDE.md, the seed, `SIM_MACHINES`; stated, not measured |

## Flags: claims I could not trace, or that need care

1. **Test counts are not in any result file.** "1,217 engine tests", "34 browser tests" and "32 of
   32 planted errors caught by the gate self-test" come only from command output (`make gate`,
   `make gate-selftest`). They are **left out**. To use them, the gate would first have to write
   its counts to a file in `eval/results/` that the render reads.
2. **"Plans break every day" was dropped** (no measurement); shot 2 says "Plan it. Check it. Run it.",
   which describes features.
3. **N1 is from 20 held-out messages**, a small set; the caption says "20 unseen messages" so the
   number is not overstated. The larger all-set figure (92 % of 75) mixes in the dev set that the
   prompt was tuned on, so it is not used.
4. **N5 to N7 and N11 to N12 are seeded benchmarks**, not the demo shop; their source lines say
   so ("40-job benchmark", "seeded 80-job plans").
5. **Shot 9 is an illustration** of a planted error, labelled as such; the measured claim is N4.
6. **Dispatch runs against simulated machines**; shots 14 to 16 carry the "Simulated machines" label.

## Changes after review (2026-11-03)

- **Re-plan baseline (shot 13, N6):** the first draft compared 3.7 jobs moved with 22.3, the
  "none" run, which re-solves from scratch. The M6 report (`eval/results/REPLAN.md`) names
  "none, approved hint" (14.3) as the fair baseline: no re-planning costs, but the search starts
  from the approved plan. The shot now uses 14.3 and its source line names that baseline.
  "Same lateness" was checked seed by seed: lateness minutes (2896, 0, 3631), late counts (3, 0, 2)
  and solver status (all OPTIMAL) are identical for the two runs, so the claim holds per seed, not
  only on average.
- **Shot 16:** fixed by cutting words only ("Unsafe calls passed: 0 of 10." / "Without Proceed: 0",
  9 words in 3.6 s). Length unchanged.
- **Shot 17:** cutting words alone could not fit both the comparison and the win count, so it was
  split into two beats (17a, 17b) and lengthened by 1.8 s (within the 1 to 2 s allowed). It now
  names the earliest-due-date baseline and 80 jobs on screen; "15 of 15" says in its source line that
  it covers 20 to 80-job plans. No caption's reading time was shortened.
- **Total:** 75.0 s to 76.8 s (limit 80 s). Shot 18 moves to 72.6 to 76.8 s.

## Changes while building (2026-11-03)

- **Shot 7 is 5.4 s, not 4.8 s** (one beat longer): counting the number as a word, its 13 words need
  4.8 s of reading and only 4.4 s were left after the number settles. Total 77.4 s (limit 80 s);
  every later shot moves 0.6 s.
- **Shot 4** shows the name only; "fictional shop · fake data" is on the end card (open point closed).
- **Shot 5** uses the customer's own view of the quote (message, then the lines read from it); the
  "from message" source badges are on the staff review, which shot 6 does not need.
- **Shot 6's AI side** shows the model's due *rule* ("by Friday"), not a date: the date is resolved by
  code, so a date chip on the AI side would have been wrong.
- **Shot 15's machine card** is drawn from the real run: CNC-1 was idle in the proposal still and
  running after Proceed (`dispatch-machine` still); the card shows that change in place.
- **Camera targets** come from boxes measured during the stills run (`video/public/stills/boxes.json`),
  not from coordinates read off the screen by eye.

## Sound (after the full render)

You chose sound effects on the animations instead of background music (open point closed). Eleven
short sounds are made from formulas by `scripts/sfx.mjs` with the repo's ffmpeg (nothing downloaded,
no licence to track) and each is cued inside its shot on the frame its animation starts:

| Shot | Animation | Sound |
|---|---|---|
| 1 | lines sweep in; six machine pills appear | whoosh; six ticks |
| 2 | "Plan it." "Check it." "Run it." | a low hit per word |
| 3 | three screens rise | three swishes |
| 4 | the name card | pop |
| 5 | zoom to the message, pan to the lines | whoosh, swish |
| 6 | the boundary line draws; four chips land | swish; four pops |
| 7, 10, 13, 16, 17a, 17b | each measured number | hit |
| 8 | zoom to the check badge; "passed" | whoosh; confirm |
| 9 | the bar slides over; the check fails | swish; error |
| 11 | push-in; the words are typed | whoosh; keys |
| 12 | cut to Approve; the press | swish; click |
| 14 | push-in; the press on Proceed | whoosh; click |
| 15 | the logged call lights; CNC-1 flips to Running | tick; confirm |
| 17a | "ours" arrives after the arrow | tick |
| 18 | the end card types out | keys |

Captions get no sound (one per word would be busy), and the chapter dissolves get none of their own.
Checked after the render: all 84 cues start on their frame and no sound plays anywhere else.
