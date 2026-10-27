# File checker evaluation (M7)

Written by `make eval` (2026-10-27). Code only: no model is called. Labels follow
`eval/datasets/files_labelling.md`; the blind set was written and labelled by a
fresh-context agent that never saw the checker. Thresholds: `config/files.toml`.

**False pass** = a file labelled broken (overall fail) that the checker passed. A broken
file shown as a warning is counted apart: staff see it, but it is not a fail.

| | dev (builder) | dev (blind) | held out (blind) |
|---|---|---|---|
| Models | 23 | 12 | 12 |
| Overall verdict agrees | 23/23 (100 %) | 12/12 (100 %) | 12/12 (100 %) |
| **False pass rate** (broken passed) | 0/10 (0 %) | 0/6 (0 %) | 0/4 (0 %) |
| Broken shown only as warning | 0/10 (0 %) | 0/6 (0 %) | 0/4 (0 %) |
| False alarm (valid file failed) | 0/5 (0 %) | 0/5 (0 %) | 0/3 (0 %) |
| Size within 0.01 mm | 19/19 (100 %) | 11/11 (100 %) | 11/11 (100 %) |
| Slowest file (s) | 0.73 | 0.00 | 0.00 |

## Agreement per check

Agreement, then false passes / files labelled fail for that check.

| Check | dev (builder) | dev (blind) | held out (blind) |
|---|---|---|---|
| parse | 23/23 (100 %); 0 false pass of 4 | 12/12 (100 %); 0 false pass of 1 | 12/12 (100 %); 0 false pass of 1 |
| units | 23/23 (100 %); none labelled fail | 12/12 (100 %); none labelled fail | 12/12 (100 %); none labelled fail |
| watertight | 23/23 (100 %); 0 false pass of 2 | 12/12 (100 %); 0 false pass of 2 | 12/12 (100 %); 0 false pass of 2 |
| fits | 23/23 (100 %); 0 false pass of 2 | 12/12 (100 %); 0 false pass of 2 | 12/12 (100 %); 0 false pass of 1 |
| walls | 23/23 (100 %); 0 false pass of 2 | 12/12 (100 %); 0 false pass of 1 | 12/12 (100 %); none labelled fail |
| overhangs | 23/23 (100 %); none labelled fail | 12/12 (100 %); none labelled fail | 12/12 (100 %); none labelled fail |
| loose_parts | 23/23 (100 %); none labelled fail | 12/12 (100 %); none labelled fail | 12/12 (100 %); none labelled fail |

## Every disagreement

**dev (builder):** none.

**dev (blind):** none.

**held out (blind):** none.

