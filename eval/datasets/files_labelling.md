# Labelling guide: file checker test models (M7)

Each test model is a 3D file (STL or 3MF) made by a script, plus one label line saying what a
careful person expects each check to say. Labels come from how the model was **designed** (you
know you made a 0.6 mm plate), never from running the checker.

Thresholds are the shop settings in `config/files.toml`; the figures you need are copied here.

## Machines (build volume in mm, x y z)
| Process | Machines |
|---|---|
| fdm | 256 x 256 x 256 (three of them), 350 x 350 x 400 |
| resin | 218 x 123 x 235 |
| cnc | 400 x 300 x 150 |

## Checks and how to label them
Every label gives each check one of `pass`, `warn`, `fail`, `skip`.

| Check | pass | warn | fail | skip |
|---|---|---|---|---|
| `parse` | the file reads and has at least one triangle | (never) | empty, truncated, not a mesh, 3MF without a model, 3MF containing a `<!DOCTYPE`, more than 300,000 triangles | (never) |
| `units` | largest side of the box around the part is between 3 mm and 2000 mm | largest side under 3 mm or over 2000 mm (probably inches, cm or metres) | (never) | parse failed |
| `watertight` | closed: every edge belongs to exactly two triangles that run it in opposite directions, and faces point outwards | closed and consistent, but every face points inwards (inside out) | any edge used by one triangle, or by three or more, or twice in the same direction (holes, flipped single faces, non-manifold edges) | parse failed |
| `fits` | the box around the part, with its sides sorted, fits inside the sorted build volume of at least one machine of the label's process (equal counts as fitting) | (never) | fits no machine of that process | parse failed |
| `walls` | no thin wall (see below) | thinner than the warn figure, but not the fail figure | thinner than the fail figure | parse failed, or watertight is `fail` |
| `overhangs` | steep downward surface is at most 10 % of the total surface | more than 10 % | (never) | parse failed, or process is cnc |
| `loose_parts` | one connected shell | two or more separate shells (pieces sharing no vertex) | (never) | parse failed |

Vertices closer than 0.0001 mm count as the same vertex.

**Walls.** Thickness is measured from the surface straight inwards to the opposite surface. A
wall counts as thin only when the thin surface adds up to more than 4 mm² (so sharp edges do
not count). Figures in mm:

| Process | fail below | warn below |
|---|---|---|
| fdm | 0.8 | 1.0 |
| resin | 0.4 | 0.6 |
| cnc | 0.5 | 0.8 |

**Overhangs.** A triangle counts when it faces downwards more steeply than the process allows,
in the orientation the file was saved in (z is up): fdm counts surfaces tilted more than 45°
from vertical, resin more than 60° from vertical. In normal terms: the outward normal's z
component is below -0.707 (fdm) or -0.866 (resin). Triangles lying flat on the lowest z of the
part (within 0.01 mm) sit on the bed and do not count. The share is counted area / total area.

**Units in 3MF.** A 3MF `unit` attribute (micron, millimeter, centimeter, inch, foot, meter) is
applied before any check. STL has no unit: numbers are read as mm.

**Overall.** `fail` if any check fails; else `warn` if any check warns; else `pass`. A
"broken" model is one whose overall label is `fail`.

## Label format (one JSON object per line)
```json
{"id": "b01", "file": "models/b01.stl", "split": "dev", "process": "fdm",
 "kind": "valid", "description": "40 mm cube",
 "expected": {"parse": "pass", "units": "pass", "watertight": "pass", "fits": "pass",
              "walls": "pass", "overhangs": "pass", "loose_parts": "pass"},
 "overall": "pass", "size_mm": [40, 40, 40]}
```
`kind` is `valid`, `broken` or `borderline` (close to a threshold on purpose). `size_mm` is the
box around the part in mm (x, y, z, after any 3MF unit), or `null` when parsing fails.
