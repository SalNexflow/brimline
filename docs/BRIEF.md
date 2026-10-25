# Brimline: project brief

Production planning for made-to-order 3D-print and CNC shops.
A web platform that turns a messy customer request into a quote, plans the work across machines with a constraint solver,
proves every plan is valid with an independent checker, and re-plans when something breaks.

- **Time:** 8 to 10 weeks
- **Difficulty:** high
- **Best for roles:** software engineer with AI, AI R&D, full-stack AI
- **Data:** all fake: shop, customers, orders, generated 3D models

## 1. What it is
Brimline is a web platform for a **fictional** made-to-order 3D-print and CNC service shop. A customer sends a messy request and a 3D model file.
Brimline carries the job through the whole chain: quote, order, schedule, materials, disruptions, and a final comparison of quoted against actual results.

The heart of it is the **Production Brain**:
- a constraint solver that plans every job across printers and shifts,
- an **independent checker** that proves each plan is valid,
- a **re-planner** that repairs the day when a machine fails or a delivery is late.

AI has a narrow, safe role. It reads language (quote requests, disruption messages, search questions) and explains results.
**Code decides** prices, dates, permissions, and schedules. That split is the main design idea.

The name: a brim is the thin outline a 3D printer lays down so a print sticks to the bed. The logo mark is a part resting on its brim line.

## 2. Why we are building it
Small production shops share the same pains, and most software leaves planning to people dragging bars on a calendar:
- **Scheduling by hand.** Nothing checks whether a machine is overbooked or whether a rush job should jump the queue.
- **Materials arrive late.** Jobs get scheduled before the filament or resin is actually there.
- **Breakdowns cause chaos.** Re-planning is guesswork, and customer dates move without anyone deciding that on purpose.
- **Slow, inconsistent quotes.** Requests arrive as messy messages and the same job is priced differently by different people.
- **File problems found late.** A model with thin walls or the wrong size is found after the job has started.
- **No learning loop.** Shops rarely compare what they quoted with what the job really cost.

### Where the idea comes from
In October 2026, public pages of YoPrint (print-shop management software) were read. It covers quotes, orders, a pricing engine, inventory, and purchase orders.
Its production page describes list, calendar, and Gantt views where users drag bars to reschedule, and does not describe automatic scheduling, press capacity limits, or conflict detection.
Brimline explores that gap in a different industry (3D printing) with fake data.
**Caveat:** these were marketing pages, so a missing description is not proof the product lacks the feature. Verify before claiming anything.
Brimline is not affiliated with YoPrint and does not copy its product.

## 3. Why it is important
- **For a shop:** fewer late jobs, faster and more consistent quotes, fewer wasted prints, visible profit leaks.
- **It cannot be done in low-code.** Optimization under constraints, independent verification, stable re-planning, and permission-safe AI are real engineering.
- **It proves the right AI habit:** the model understands language and explains; code decides and verifies.
- **It gives measurable claims,** such as lateness and changeovers against a baseline, instead of "it works".
- **It is a real web app,** which is what a software engineer posting asks you to show.
- **It reuses strengths** (solver work, independent checkers, human approval, audit trails, frontend) in a new domain.

## 4. Who uses it
| Who | How they use it |
|---|---|
| Customer | Sends a request and a model file, sees the quote, tracks the order. |
| Front-desk staff | Reviews the AI-drafted quote, fixes details, sends it in minutes. |
| Production planner | Runs the board, reads the plan, approves re-plans. |
| Machine operator | Sees the next jobs per machine and marks them started, done, or failed. |
| Shop owner | Watches lateness, margin, failure rate, and which jobs are underquoted. |
| The builder (you) | A flagship portfolio project: optimization, verification, safe AI, product UI. |

## 5. The demo story
1. Customer sends a message, e.g. "20 phone stands, black PETG, need by Friday", plus a 3D model file.
2. AI drafts a structured quote. Code calculates the price from rules. A person approves.
3. File checker measures the model (watertight? fits the printer? walls too thin?). Vision advice is labelled as advice.
4. The approved order becomes jobs. The scheduler plans them across printers and shifts, respecting deadlines, materials, and rush jobs.
5. The independent checker re-validates every rule without using the scheduler's logic.
6. A manager types "printer 3 jammed until 5pm". The system re-plans only what is affected, shows a before and after diff, and waits for approval.
7. After the job, quoted versus actual cost and time show where the shop loses money.

## 6. How it is used (walkthrough by role)
1. **Customer** submits a request: pastes a message and uploads a model file.
2. **Front desk** opens the draft quote. Uncertain and missing fields are highlighted, the price comes from the price table, staff edit and approve.
3. **File report:** each check shows pass, warning, or fail with a plain reason. Staff can override a warning; the reason is logged.
4. **Planner** opens the Board and clicks Plan day. The plan appears as bars per printer with an independent-check badge. Approve it.
5. **Operator** works the queue and marks jobs started, done, or failed. Real times and failures feed back into planning.
6. **Something breaks.** The planner types a plain message. Brimline shows how it understood it (printer, start, end), then a diff of what moves, and waits.
7. **Approve or discard** the re-plan. Approval is recorded in the audit log with who and when.
8. **Owner** reviews Reports: quoted versus actual, failed print rate, late jobs. Search answers questions like "jobs due this week not printed yet".

## 7. Modules
| Module | What it does | AI or code | Proof you collect |
|---|---|---|---|
| Quote builder | Messy message to structured quote | AI reads, code prices | Field accuracy on 40+ requests; zero model-set prices |
| File checker | Measures STL or 3MF: watertight, fits, thin walls, overhangs | Code measures; vision advice labelled | Agreement with hand labels on 30+ models; false pass rate |
| Scheduler | Assigns tasks to printers and times | Solver (code) | Late jobs, lateness, changeovers vs baselines |
| Independent checker | Re-validates a plan from raw inputs | Code only | Adversarial and mutation catch rate |
| Re-planner | Disruption text to event, re-solve, diff | AI parses, solver decides | Parse accuracy; lateness vs churn |
| Shortage planning | Material arrival limits starts; suggests purchases | Code | Blocked jobs avoided |
| Search | Question to typed filter, permissions in code | AI reads, code queries | Accuracy on 50+; attacks blocked |
| Quoted vs actual | Compares estimates with outcomes and failed prints | Code | Underquote detection; failure rate |
| Quality gate | Automated checks, defect log, fresh-session review | Process | Defects logged and where caught |

## 8. AI versus code (the rule behind the design)
| Task | Who decides | Why |
|---|---|---|
| Read a customer message | AI | A language task. Output is schema-validated before use. |
| Set a price | Code | Must be exact and auditable. A model can be talked into a discount. |
| Work out what "this week" means | Code | Dates must be unambiguous. AI picks a named rule; code computes the dates. |
| Decide which printer does which task | Solver | An optimization with hard constraints, not a judgment call. |
| Verify the plan | Independent checker | Must not share assumptions with what it checks. |
| Decide who may see which orders | Code | Security. Enforced on every query after any AI step. |
| Explain why a plan changed | AI, from the diff only | Plain-language summary grounded in computed facts. |
| Approve a re-plan or a quote | A human | Risky actions need approval enforced in code. |

## 9. Architecture
| Part | Technology (suggested) | Job |
|---|---|---|
| Web app | Next.js, React, TypeScript | Screens, demo roles, quotes, orders, search, the board, approvals |
| Engine service | Python, FastAPI, OR-Tools | Scheduler, independent checker, mesh file checker, planning |
| Database | PostgreSQL | All data, plus an append-only audit log enforced by a trigger |
| AI gateway | One module, model names in config | Every model call goes here: schema validation, cost and latency logging |
| Eval harness | Datasets and scoring scripts | Runs every evaluation and writes results to one file |

Data flow: the web app calls the engine over HTTP. The engine reads and writes PostgreSQL. Models are called only through the AI gateway, and their output is validated before anything uses it.

## 10. How the scheduler works
1. **Model the work.** Each order becomes jobs; each job becomes ordered tasks: file prep, print, cool-down, post-processing, quality check, pack. Each task needs a resource type.
2. **Estimate durations.** Setup time plus print time (a simple formula from volume and settings at first; a slicer can replace it later) plus cool-down.
3. **Hard constraints.** One task at a time per machine. Tasks follow their order. The machine must fit the part and support the material. A task cannot start before its materials arrive. Finished and running tasks are fixed.
4. **Weighted goals.** Few late jobs and rush jobs first, few material changeovers, little idle time and overtime, few changes when re-planning.
5. **Solve with CP-SAT** (Google OR-Tools) with a fixed seed and time limit so a run can be repeated exactly.
6. **Compare with baselines.** First-come-first-served and greedy earliest-due-date, on seeded instances of 20, 40, and 80 jobs.
7. **Report metrics.** Late jobs, total lateness, changeovers, machine utilisation, finish time.
8. **Re-plan.** Fix what is done or running, apply the disruption, re-solve the rest, and penalise moving dates already told to customers. Show the diff.

## 11. How the independent checker works
1. **Separate code.** It must not import anything from the scheduler. Enforce this with a test.
2. **Recompute from raw inputs.** It reads the orders, machines, materials, and the proposed plan, and recomputes durations itself.
3. **Check every rule.** No overlaps, correct task order, machine fits the part, material compatible and available, finished tasks unchanged, shift rules, and deadlines (lateness is reported, not hidden).
4. **Recompute the metrics** so the scheduler cannot overstate its own result.
5. **Prove it catches errors.** Write 25 or more adversarial cases by hand, then deliberately corrupt valid plans in many ways (mutation tests) and require the checker to catch every one.
6. **Keep the real catches.** When it finds a genuine scheduler bug, record it. That is the strongest story in the project.

## 12. How the file checker works
1. Parse STL or 3MF; reject corrupt or unsupported files with a clear message.
2. Measure with code: watertight surface, sensible scale and units, size against each printer's build volume, estimated wall thickness, share of steep overhangs, volume, loose parts.
3. Thresholds are shop settings with a stated source, since guidelines vary by printer and material.
4. A vision model may comment on a rendered preview. It is shown as advice, never as a verdict.
5. Test with models generated by code (cubes, thin plates, open meshes) or free models, so there is no copyright risk.
6. Label every test model yourself. The most important number is the **false pass rate**: bad files the checker let through.

## 13. Data model (key tables)
| Table | Purpose |
|---|---|
| customers, users | Fake customers and demo roles (staff, planner, operator, customer) |
| printers, shifts | Machines with type, build volume, supported materials, and working hours |
| materials, stock, suppliers, purchase_orders | What is on hand, what is arriving, and when |
| price_rules | Rules that turn a structured quote into a price. Editable, dated. |
| quotes, quote_lines, orders, jobs | From request to approved work |
| tasks | Planned and actual start, end, machine, and status for each step |
| files, file_checks | Uploads and the result of each check |
| schedules, assignments | Versioned plans, so any plan can be compared with another |
| disruptions | Typed events: machine down, material delayed, rush job, cancellation |
| audit_log | Append-only record of every approval and write, enforced by a trigger |
| eval_runs | Stored evaluation results, so numbers are traceable |

## 14. Evaluation plan
| Part | Dataset | Metric |
|---|---|---|
| Quote builder | 40+ messy requests with known fields, incl. vague, contradictory, and instruction-injecting ones | Field accuracy; missing details flagged vs guessed; injection resisted |
| Disruption parser | 30+ typed messages | Event, machine, and time accuracy; ambiguous ones flagged |
| Search | 50+ questions plus attack attempts | Correct filter; attacks blocked; unclear ones flagged |
| File checker | 30+ hand-labelled models | Agreement per check; false pass rate |
| Scheduler | Seeded instances of 20, 40, and 80 jobs | Late jobs, total lateness, changeovers vs two baselines |
| Checker | 25+ adversarial cases plus mutations | Catch rate; false alarms |
| Re-planner | Scripted disruption scenarios | Lateness vs how many jobs moved; checker passes |

Rules: keep a held-out set you never tune on; change one thing at a time; every README number comes from `make eval` or `make bench`.

## 15. Résumé claims to earn (fill in only measured numbers)
- **Scheduler:** an OR-Tools scheduler reduced late jobs from [X] to [Y] and material changeovers by [Z%] against an earliest-due-date baseline on [N] seeded instances.
- **Checker:** an independent schedule checker with [N] adversarial cases and [N] mutation tests caught [N] real scheduler defects.
- **Safe AI:** models only parse language and explain diffs while prices, dates, and permissions are enforced in code: [X%] field accuracy on [N] messy requests; [N] of [N] access-widening attacks blocked.

## 16. Honest limits
- All data is synthetic. Say so, and say what you would test on real shop data.
- Print time is estimated with a simple formula. A real slicer would be more accurate; say so in the README.
- Research on YoPrint came from marketing pages. Treat the gap as a hypothesis until verified.
- No affiliation with any real company. Do not copy anyone's branding, screens, or wording.
- Check licenses for any free 3D model you use.

## 17. Definition of done
- A stranger can clone the repo and reproduce the headline tables with documented commands.
- The README shows results against baselines with real numbers, plus screenshots and a demo video.
- The independent checker has adversarial and mutation tests, and its real catches are listed.
- Prices, dates, and permissions are enforced in code, with tests.
- Risky actions need approval, and every approval is in the audit log.
- The defect log has real entries, and the builder can explain three of them from memory.
- The builder can explain every design choice without reading the code.
