# File checker evaluation (M7)

Written by `make eval` (2026-10-28). Code only: no model is called. Labels follow
`eval/datasets/files_labelling.md`; the blind set was written and labelled by a
fresh-context agent that never saw the checker. Thresholds: `config/files.toml`.

**False pass** = a file labelled broken (overall fail) that the checker passed. A broken
file shown as a warning is counted apart: staff see it, but it is not a fail.

| | dev (builder) | dev (blind) | held out (blind) |
|---|---|---|---|
| Models | 27 | 12 | 12 |
| Overall verdict agrees | 27/27 (100 %) | 12/12 (100 %) | 12/12 (100 %) |
| **False pass rate** (broken passed) | 0/12 (0 %) | 0/6 (0 %) | 0/4 (0 %) |
| Broken shown only as warning | 0/12 (0 %) | 0/6 (0 %) | 0/4 (0 %) |
| False alarm (valid file failed) | 0/5 (0 %) | 0/5 (0 %) | 0/3 (0 %) |
| Size within 0.01 mm | 21/21 (100 %) | 11/11 (100 %) | 11/11 (100 %) |
| Slowest file (s) | 0.77 | 0.02 | 0.02 |

## Agreement per check

Agreement, then false passes / files labelled fail for that check.

| Check | dev (builder) | dev (blind) | held out (blind) |
|---|---|---|---|
| parse | 27/27 (100 %); 0 false pass of 6 | 12/12 (100 %); 0 false pass of 1 | 12/12 (100 %); 0 false pass of 1 |
| units | 27/27 (100 %); none labelled fail | 12/12 (100 %); none labelled fail | 12/12 (100 %); none labelled fail |
| watertight | 27/27 (100 %); 0 false pass of 2 | 12/12 (100 %); 0 false pass of 2 | 12/12 (100 %); 0 false pass of 2 |
| fits | 27/27 (100 %); 0 false pass of 2 | 12/12 (100 %); 0 false pass of 2 | 12/12 (100 %); 0 false pass of 1 |
| walls | 27/27 (100 %); 0 false pass of 2 | 12/12 (100 %); 0 false pass of 1 | 12/12 (100 %); none labelled fail |
| overhangs | 27/27 (100 %); none labelled fail | 12/12 (100 %); none labelled fail | 12/12 (100 %); none labelled fail |
| loose_parts | 27/27 (100 %); none labelled fail | 12/12 (100 %); none labelled fail | 12/12 (100 %); none labelled fail |

## Every disagreement

**dev (builder):** none.

**dev (blind):** none.

**held out (blind):** none.

