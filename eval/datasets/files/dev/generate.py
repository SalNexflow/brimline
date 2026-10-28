"""Dev test models for the file checker, written by the builder (the blind set is in ../blind).
Labels come from how each shape is designed (eval/datasets/files_labelling.md), never from
running the checker. Run with the engine's Python:

    services/engine/.venv/Scripts/python.exe eval/datasets/files/dev/generate.py
"""

import json
from pathlib import Path

import numpy as np

from brimline_engine.files import samples as s

HERE = Path(__file__).parent
ALL_PASS = {
    c: "pass" for c in ("parse", "units", "watertight", "fits", "walls", "overhangs", "loose_parts")
}
SKIPPED = {c: "skip" for c in ALL_PASS} | {"parse": "fail"}


def label(
    i: int,
    file: str,
    process: str,
    kind: str,
    description: str,
    size: list[float] | None,
    **changes: str,
) -> dict[str, object]:
    expected = (SKIPPED if size is None else ALL_PASS) | changes
    statuses = set(expected.values())
    overall = "fail" if "fail" in statuses else "warn" if "warn" in statuses else "pass"
    return {
        "id": f"d{i:02d}",
        "file": f"models/{file}",
        "split": "dev",
        "process": process,
        "kind": kind,
        "description": description,
        "expected": expected,
        "overall": overall,
        "size_mm": size,
    }


def main() -> None:
    models = HERE / "models"
    models.mkdir(exist_ok=True)
    cube = s.box(40, 40, 40)
    t_profile = [(0, 0), (10, 0), (10, 30), (30, 30), (30, 40), (-20, 40), (-20, 30), (0, 30)]
    fin = np.array([[[0, 0, 40], [40, 0, 40], [20, 0, 60]]], dtype=np.float64)
    cases: list[tuple[str, bytes, dict[str, object]]] = []

    def add(
        file: str,
        data: bytes,
        process: str,
        kind: str,
        description: str,
        size: list[float] | None,
        **changes: str,
    ) -> None:
        cases.append(
            (file, data, label(len(cases) + 1, file, process, kind, description, size, **changes))
        )

    add("d01.stl", s.binary_stl(cube), "fdm", "valid", "40 mm cube", [40, 40, 40])
    add(
        "d02.stl",
        s.text_stl(s.box(100, 100, 0.6)),
        "fdm",
        "broken",
        "100 x 100 mm plate, 0.6 mm thick (under 0.8)",
        [100, 100, 0.6],
        walls="fail",
    )
    add(
        "d03.3mf",
        s.three_mf(s.box(100, 100, 0.9)),
        "fdm",
        "borderline",
        "plate 0.9 mm thick (between 0.8 and 1.0)",
        [100, 100, 0.9],
        walls="warn",
    )
    add(
        "d04.stl",
        s.binary_stl(cube[1:]),
        "fdm",
        "broken",
        "40 mm cube with one triangle missing (a hole)",
        [40, 40, 40],
        watertight="fail",
        walls="skip",
    )
    add(
        "d05.stl",
        s.text_stl(s.flip(s.box(30, 30, 30))),
        "resin",
        "borderline",
        "30 mm cube, inside out",
        [30, 30, 30],
        watertight="warn",
    )
    add(
        "d06.stl",
        s.binary_stl(s.box(300, 60, 20)),
        "fdm",
        "valid",
        "300 mm bar: fits only the large printer",
        [300, 60, 20],
    )
    add(
        "d07.stl",
        s.binary_stl(s.box(300, 60, 20)),
        "resin",
        "broken",
        "the same 300 mm bar on resin (235 mm at most)",
        [300, 60, 20],
        fits="fail",
    )
    add(
        "d08.stl",
        s.binary_stl(s.box(0.04, 0.04, 0.04)),
        "fdm",
        "borderline",
        "40 mm cube saved in metres (0.04): tiny; its 0.04 mm walls cover under 4 mm²",
        [0.04, 0.04, 0.04],
        units="warn",
    )
    add(
        "d09.3mf",
        s.three_mf(s.box(1.5, 1.5, 1.5), unit="inch"),
        "fdm",
        "valid",
        "1.5 inch cube in a 3MF with unit inch: 38.1 mm",
        [38.1, 38.1, 38.1],
    )
    add(
        "d10.3mf",
        s.three_mf(np.concatenate([s.box(20, 20, 20), s.box(20, 20, 20, (40, 0, 0))])),
        "fdm",
        "borderline",
        "two 20 mm cubes 20 mm apart",
        [60, 20, 20],
        loose_parts="warn",
    )
    add(
        "d11.stl",
        s.binary_stl(s.extrude(t_profile, 20)),
        "fdm",
        "borderline",
        "T shape: underside of the bar is 800 of 5200 mm² (15.4 %)",
        [50, 20, 40],
        overhangs="warn",
    )
    add(
        "d12.stl",
        s.binary_stl(s.hollow_box(50, 50, 50, 0.5)),
        "resin",
        "borderline",
        "hollow 50 mm box, 0.5 mm walls (resin warn under 0.6); cavity ceiling 2401 of 29406 mm² (8.2 %)",
        [50, 50, 50],
        walls="warn",
        loose_parts="warn",
    )
    add("d13.stl", s.binary_stl(cube)[:-20], "fdm", "broken", "binary STL cut short", None)
    add(
        "d14.3mf",
        s.three_mf(cube, doctype=True),
        "fdm",
        "broken",
        "3MF with a DOCTYPE and ENTITY",
        None,
    )
    add(
        "d15.stl",
        s.text_stl(np.concatenate([cube, fin])),
        "fdm",
        "broken",
        "40 mm cube with a fin on a top edge (edge used by three triangles)",
        [40, 40, 60],
        watertight="fail",
        walls="skip",
    )
    add(
        "d16.stl",
        s.text_stl(s.box(100, 50, 20)),
        "cnc",
        "valid",
        "100 x 50 x 20 mm block for the mill",
        [100, 50, 20],
        overhangs="skip",
    )
    add("d17.stl", b"", "fdm", "broken", "empty file", None)
    add(
        "d18.stl",
        b"this is a shopping list, not a model\n",
        "fdm",
        "broken",
        "text file named .stl",
        None,
    )
    add(
        "d19.stl",
        s.binary_stl(s.box(400, 20, 20)),
        "fdm",
        "borderline",
        "400 mm bar: exactly the large printer's height, turned",
        [400, 20, 20],
    )
    add(
        "d20.stl",
        s.binary_stl(s.box(401, 20, 20)),
        "fdm",
        "borderline",
        "401 mm bar: 1 mm too long for any fdm printer",
        [401, 20, 20],
        fits="fail",
    )
    circle = [
        (30 + 30 * np.cos(a), 30 + 30 * np.sin(a))
        for a in np.linspace(0, 2 * np.pi, 64, endpoint=False)
    ]
    add(
        "d21.stl",
        s.binary_stl(s.extrude(circle, 40)),
        "fdm",
        "valid",
        "cylinder lying on its side, 60 mm across, 64 sides: curved underside is 1/4 of the round surface, below the 45° line",
        [60, 40, 60],
        overhangs="warn",
    )
    # Over 4,000 triangles: the wall check samples rays instead of testing every face.
    grid = np.concatenate([s.box(2, 2, 2, (i * 4, j * 4, 0)) for i in range(25) for j in range(25)])
    add(
        "d22.stl",
        s.binary_stl(grid),
        "fdm",
        "borderline",
        "625 separate 2 mm cubes (7,500 triangles): walls 2 mm",
        [98, 98, 2],
        loose_parts="warn",
    )
    plates = np.concatenate(
        [s.box(5, 5, 0.5, (i * 8, j * 8, 0)) for i in range(25) for j in range(25)]
    )
    add(
        "d23.stl",
        s.binary_stl(plates),
        "fdm",
        "broken",
        "625 separate 5 x 5 x 0.5 mm plates (7,500 triangles): walls 0.5 mm",
        [197, 197, 0.5],
        walls="fail",
        loose_parts="warn",
    )

    # Added after the fresh-context review of M7 (DEFECT_LOG #57, #58, #59): these used to pass
    # or be misread.
    far = np.concatenate([s.box(20, 20, 20), s.box(1e15, 1e15, 1e15, (5e15, 5e15, 5e15))])
    add(
        "d24.stl",
        s.binary_stl(far),
        "fdm",
        "broken",
        "20 mm cube plus a cube 10^15 mm away (coordinates past 100 m)",
        None,
    )
    mixed = np.concatenate([s.box(20, 20, 20), s.flip(s.box(10, 10, 10, (40, 0, 0)))])
    add(
        "d25.stl",
        s.binary_stl(mixed),
        "fdm",
        "borderline",
        "20 mm cube and a separate 10 mm cube wound inside out",
        [50, 20, 20],
        watertight="warn",
        loose_parts="warn",
    )
    add(
        "d26.3mf",
        s.three_mf(s.box(10, 10, 10), copies=["-1 0 0 0 1 0 0 0 1 -30 0 0"]),
        "fdm",
        "borderline",
        "one 10 mm cube placed twice in a 3MF, the second copy mirrored",
        [50, 10, 10],
        loose_parts="warn",
    )
    add(
        "d27.3mf",
        s.three_mf(cube, doctype=True, encoding="utf-16"),
        "fdm",
        "broken",
        "3MF model in UTF-16 with a DOCTYPE",
        None,
    )

    lines = []
    for file, data, lab in cases:
        (models / file).write_bytes(data)
        lines.append(json.dumps(lab))
    (HERE / "labels.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    print(f"wrote {len(cases)} models")


if __name__ == "__main__":
    main()
