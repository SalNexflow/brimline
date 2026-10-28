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
| Slowest file (s) | 0.85 | 0.00 | 0.00 |

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

## Real models (CC0 or public domain)

Five free-licence files from Wikimedia Commons (`eval/datasets/files/real/sources.json`).
Only checks a person can judge by eye or from the size are labelled; closedness and walls
of organic shapes are not. Shown: every check's result; scored: the labelled ones.

| Model | Licence | Size (mm) | parse | units | watertight | fits | walls | overhangs | loose_parts | Labelled checks agree |
|---|---|---|---|---|---|---|---|---|---|---|
| [3d model of Sphere.stl](https://commons.wikimedia.org/wiki/File:3d_model_of_Sphere.stl) | Public domain | 341.6 x 331.8 x 331.8 | pass | pass | pass | pass | pass | warn | pass | 5/5 |
| [3D-Modell Selbstähnlichkeit 20220517.stl](https://commons.wikimedia.org/wiki/File:3D-Modell_Selbstähnlichkeit_20220517.stl) | CC0 | 2.0 x 0.5 x 3.0 | pass | **warn** | fail | pass | skip | warn | warn | 1/2 |
| [Andreaskreuz 20220723.stl](https://commons.wikimedia.org/wiki/File:Andreaskreuz_20220723.stl) | CC0 | 8.3 x 0.1 x 12.6 | pass | pass | pass | pass | fail | pass | warn | 5/5 |
| [Astronaut Astronaut1.stl](https://commons.wikimedia.org/wiki/File:Astronaut_Astronaut1.stl) | Public domain | 68.9 x 27.6 x 74.3 | pass | pass | fail | pass | skip | warn | warn | 3/3 |
| [3D-Modell Baustelle 20220717.stl](https://commons.wikimedia.org/wiki/File:3D-Modell_Baustelle_20220717.stl) | CC0 | 3.6 x 3.6 x 0.4 | pass | pass | fail | pass | skip | warn | warn | 2/2 |

Labelled checks that agree: 16/17. A result in **bold** disagrees with its label.
Two of these (the tower and the building site) are most likely modelled in centimetres. The
building site, 3.6 mm across, passes the unit check (a limit of the 3 mm rule); the tower
measures 3.0 mm, on the rule's edge, and the checker warns while the label said pass
(docs/DECISIONS.md D128).
