# Delivery slips and purchase suggestions (M9)

Generated 2026-11-01T08:07:25+00:00 by `make shortage-bench`. 5 seeded 40-job instances; 60 % of each material's grams on hand, one delivery with the rest; CP-SAT limit 5.0 s. Method: `scheduling/shortage_bench.py`.

Means over seeds. Late = late or unscheduled jobs; hours = total lateness of scheduled jobs.

| Delivery slip | No material limit (CP-SAT) | EDD | CP-SAT | CP-SAT + suggested orders | Hours late: CP-SAT / + orders | Orders suggested (in time) |
|---|---|---|---|---|---|---|
| 0 d | 0.8 | 3.2 | 1.6 | 1.4 | 41.5 / 33.4 | 1.0 (1 of 5) |
| 1 d | 0.8 | 3.8 | 2.4 | 1.8 | 87.0 / 51.8 | 1.8 (3 of 9) |
| 2 d | 0.8 | 3.8 | 3.0 | 2.0 | 178.2 / 79.3 | 2.0 (3 of 10) |
| 4 d | 0.8 | 7.8 | 6.4 | 2.2 | 384.7 / 97.9 | 4.8 (16 of 24) |

Every plan was checked by the independent checker, rule R20 included: 60 of 60 valid.

Stock mutations on the CP-SAT plans (applied / caught): stock_reduced 20/20, delivery_removed 20/20, delivery_one_minute_late 20/20.

Orders are suggested as if placed at the moment of planning; one that cannot arrive before the first short need is "not in time" (the page then says order today).
