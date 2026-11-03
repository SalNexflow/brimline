# Brimline product video: storyboard (draft for approval)

75 s, 1920 x 1080, 30 fps, captions only, CC0 music. Built in Remotion (not yet added: test shot
and render wait until the design is final). Craft rules: `.claude/skills/motion-video/SKILL.md`.

- **Beat grid:** cut points assume a 100 BPM track (a beat is 0.6 s, a bar 2.4 s); every shot
  starts on a beat. If the chosen CC0 track has another tempo, shot lengths scale to its grid.
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
| 7 | 24.0 to 28.8 | Number reveal | Number on a calm field, source line below | "85 %" + "every field right on 20 unseen messages", then "0" + "harmful errors" | 9 + 2 words, 3.5 s + 1.2 s, 4.8 s | N1, N2, N3 | blur dissolve |
| 8 | 28.8 to 33.6 | Floating window, zoom to region | Board: camera eases onto the "Independent check: passed" badge and the stat cards | "A second program checks every plan." | 6 words, 2.5 s, 3.6 s | none | hard cut |
| 9 | 33.6 to 37.2 | State change (illustration) | Abstract plan bars; one bar slides into another's time; the badge flips to "✗ machine_overlap". Labelled "planted error" | "It shares no code with the scheduler." | 7 words, 2.8 s, 3.0 s | none | match cut |
| 10 | 37.2 to 40.8 | Number reveal | The two halves of the number settle | "2,880 / 2,880" + "planted rule breaks caught" | 4 words, 1.8 s, 3.0 s | N4 | blur dissolve |
| 11 | 40.8 to 45.6 | Macro UI crop | Board, "Something went wrong?": a planner types that FDM-1 is down; the events appear as chips to confirm | "A printer goes down." | 4 words, 1.8 s, 3.6 s | none | hard cut |
| 12 | 45.6 to 50.4 | State change | Draft plan with its changes: bars shift on the timeline, the check badge passes, the cursor presses "Approve plan" | "The plan moves. A person approves." | 6 words, 2.5 s, 3.6 s | none | hard cut |
| 13 | 50.4 to 54.0 | Number reveal | "3.7" settles beside a struck-through "22.3" | "jobs moved instead of 22.3, same lateness" + small "40-job benchmark, FDM-1 down" | 7 words, 2.8 s, 3.0 s | N5, N6, N7 | blur dissolve |
| 14 | 54.0 to 58.8 | Floating window | Dispatch: the proposal card, the box ticked, "Proceed" pressed. Corner label "Simulated machines" | "An agent proposes. A person says go." | 7 words, 2.8 s, 3.6 s | none | hard cut |
| 15 | 58.8 to 62.4 | State change | The tool-call row fades in ("agent · start_task · allowed"); CNC-1's pill turns from "○ Idle" to "▶ Running" | "Code checks every call." | 4 words, 1.8 s, 3.0 s | none | hard cut |
| 16 | 62.4 to 66.0 | Number reveal | Two lines, one after the other | "0 of 10 unsafe calls got through" / "0 actions without a Proceed" | 7 + 5 words, but shown one after the other: 2.8 s then 2.2 s, **needs 5.0 s, has 3.6 s** (see open points) | N8, N9, N10 | blur dissolve |
| 17 | 66.0 to 70.8 | Number reveal | "38.4" slides to "10.8" | "late jobs per 80-job plan, vs a deadline-first rule" / "better on 15 of 15 plans" | 9 + 5 words, 3.5 s + 2.2 s, **needs 5.7 s, has 4.8 s** (see open points) | N11, N12 | hard cut |
| 18 | 70.8 to 75.0 | Typewriter + end card | Monospace caps type out, then the logo holds | "BRIMLINE" / "FICTIONAL SHOP · FAKE DATA · SIMULATED MACHINES" / "github.com/SalNexflow/brimline" | held 2.4 s | none | end |

Chapters: opening 0 to 14.4 s, AI versus code 14.4 to 28.8 s, the checker 28.8 to 40.8 s,
re-plan 40.8 to 54.0 s, dispatch 54.0 to 66.0 s, results 66.0 to 75.0 s.

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
| N6 | "22.3" | 22.3 | same | same, `costs == "none"` |
| N7 | "same lateness" | 36.3 h both | same | mean `lateness_minutes` / 60 of the two groups; the render fails unless they are equal |
| N8 | "0" (got through) | 0 | `eval/results/dispatch_deepseek-flash.json` | `summary.dev.unsafe_through + summary.heldout.unsafe_through` |
| N9 | "of 10" | 10 | same | `summary.dev.unsafe_calls + summary.heldout.unsafe_calls` |
| N10 | "0 actions without a Proceed" | 0 | same | `summary.dev.executed_without_proceed + summary.heldout.executed_without_proceed` |
| N11 | "38.4 to 10.8" | 38.4 / 10.8 | `eval/results/bench.json` | mean `late_or_unscheduled` of `main` rows with `jobs == 80`, `method == "edd"` / `"cpsat-simple"` |
| N12 | "15 of 15" | 15 / 15 | same | instances in `main` where `cpsat-simple`'s `objective` is below `edd`'s / all instances |

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

## Open points for your decision

- **Shots 16 and 17 are short of reading time** (3.6 s for 5.0 s of words; 4.8 s for 5.7 s).
  Proposal: shorten the words ("0 of 10 unsafe calls passed" / "0 without a Proceed"; "late jobs,
  80-job plans" / "better on 15 of 15"), which fits both; or take 1.2 s from shot 3.
- **Shot 4 overlaps shot 5 by 1.0 s** for its small line; alternatively drop "fictional shop · fake
  data" there, since the end card says it.
- **Music:** a CC0 track near 100 BPM with a clear build at about 54 s (dispatch) and a resolve at
  66 s; I will propose two or three with their licence pages before the test shot.
