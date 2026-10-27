"""Generate the blind, hand-labelled file-checker test set (24 models) and its labels.

Labels are written by hand below from how each model was designed. The only computing done
here is a self-check of my own geometry (closed meshes have positive volume, fan triangles
are not degenerate, the overhang share I worked out by hand matches the triangles).
Run from any folder:  python eval/datasets/files/blind/generate.py
"""

from __future__ import annotations

import json
import math
import struct
import zipfile
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
OUT = HERE / "models"

Tri = tuple[tuple[float, float, float], tuple[float, float, float], tuple[float, float, float]]


# ---------------------------------------------------------------- geometry
def prism(profile: list[tuple[float, float]], center: tuple[float, float],
          y0: float, y1: float) -> list[Tri]:
    """Extrude a CCW (x, z) profile along y. Caps are fans from `center`, which must see
    every profile vertex. Outward, counter-clockwise winding seen from outside."""
    tris: list[Tri] = []
    n = len(profile)
    cx, cz = center
    for i in range(n):
        (ax, az), (bx, bz) = profile[i], profile[(i + 1) % n]
        # fan triangle must be counter-clockwise in (x, z): no degenerate slivers
        cross = (ax - cx) * (bz - cz) - (az - cz) * (bx - cx)
        assert cross > 1e-9, "fan triangle degenerate or clockwise"
        tris.append(((cx, y0, cz), (ax, y0, az), (bx, y0, bz)))  # front cap, normal -y
        tris.append(((cx, y1, cz), (bx, y1, bz), (ax, y1, az)))  # back cap, normal +y
        a0, b0, a1, b1 = (ax, y0, az), (bx, y0, bz), (ax, y1, az), (bx, y1, bz)
        tris.append((b0, a0, a1))
        tris.append((b0, a1, b1))
    return tris


def box(x0: float, y0: float, z0: float, x1: float, y1: float, z1: float) -> list[Tri]:
    prof = [(x0, z0), (x1, z0), (x1, z1), (x0, z1)]
    return prism(prof, ((x0 + x1) / 2, (z0 + z1) / 2), y0, y1)


def flip(t: Tri) -> Tri:
    return (t[0], t[2], t[1])


def signed_volume(tris: list[Tri]) -> float:
    a = np.array(tris, dtype=float)
    return float(np.einsum("ij,ij->i", a[:, 0], np.cross(a[:, 1], a[:, 2])).sum() / 6.0)


def overhang_share(tris: list[Tri], nz_limit: float) -> float:
    """Self-check of my hand-worked share (not a checker: no bed rule beyond z-min faces)."""
    a = np.array(tris, dtype=float)
    n = np.cross(a[:, 1] - a[:, 0], a[:, 2] - a[:, 0])
    area = np.linalg.norm(n, axis=1) / 2
    nz = n[:, 2] / np.linalg.norm(n, axis=1)
    zmin = a[:, :, 2].min()
    on_bed = np.all(np.abs(a[:, :, 2] - zmin) < 0.01, axis=1)
    counted = (nz < nz_limit) & ~on_bed
    return float(area[counted].sum() / area.sum())


def t_shape(length: float) -> list[Tri]:
    # stem 10 wide x 20 tall, bar 20 wide x 5 thick on top; undersides 2 x 5 mm wide
    prof = [(-5, 0), (5, 0), (5, 20), (10, 20), (10, 25), (-10, 25), (-10, 20), (-5, 20)]
    return prism(prof, (0, 21), 0, length)


def chamfer(deg: float) -> list[Tri]:
    # flat 20 mm bottom, sides slope outwards at `deg` from vertical for 20 mm, then 10 mm
    # vertical walls, flat top; 40 mm long. No acute corners, so no knife edges.
    d = 20 * math.tan(math.radians(deg))
    prof = [(-10, 0), (10, 0), (10 + d, 20), (10 + d, 30), (-10 - d, 30), (-10 - d, 20)]
    return prism(prof, (0, 15), 0, 40)


# ---------------------------------------------------------------- writers
def normal(t: Tri) -> tuple[float, float, float]:
    a = np.array(t, dtype=float)
    n = np.cross(a[1] - a[0], a[2] - a[0])
    ln = float(np.linalg.norm(n))
    return tuple(float(v) for v in (n / ln if ln else n))  # type: ignore[return-value]


def binary_stl(tris: list[Tri]) -> bytes:
    out = bytearray(b"brimline blind test model".ljust(80, b" "))
    out += struct.pack("<I", len(tris))
    for t in tris:
        out += struct.pack("<3f", 0.0, 0.0, 0.0)  # normals as zeros; checkers use winding
        for v in t:
            out += struct.pack("<3f", *v)
        out += b"\0\0"
    return bytes(out)


def ascii_stl(tris: list[Tri], name: str) -> bytes:
    lines = [f"solid {name}"]
    for t in tris:
        n = normal(t)
        lines.append(f"  facet normal {n[0]:.6e} {n[1]:.6e} {n[2]:.6e}")
        lines.append("    outer loop")
        for v in t:
            lines.append(f"      vertex {v[0]:.6f} {v[1]:.6f} {v[2]:.6f}")
        lines.append("    endloop")
        lines.append("  endfacet")
    lines.append(f"endsolid {name}")
    return ("\n".join(lines) + "\n").encode("ascii")


def threemf(tris: list[Tri], unit: str = "millimeter", doctype: bool = False,
            duplicate_index: int | None = None) -> bytes:
    verts: dict[tuple[float, float, float], int] = {}
    faces: list[tuple[int, int, int]] = []
    for t in tris:
        idx = []
        for v in t:
            key = tuple(round(c, 9) for c in v)
            if key not in verts:
                verts[key] = len(verts)  # type: ignore[index]
            idx.append(verts[key])  # type: ignore[index]
        faces.append((idx[0], idx[1], idx[2]))
    if duplicate_index is not None:
        faces.append(faces[duplicate_index])
    vx = "\n".join(f'          <vertex x="{v[0]:.6f}" y="{v[1]:.6f}" z="{v[2]:.6f}"/>' for v in verts)
    fx = "\n".join(f'          <triangle v1="{a}" v2="{b}" v3="{c}"/>' for a, b, c in faces)
    head = '<?xml version="1.0" encoding="UTF-8"?>\n'
    if doctype:
        head += '<!DOCTYPE model [<!ENTITY note "brimline">]>\n'
    model = (
        head
        + f'<model unit="{unit}" xml:lang="en-US" '
        'xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02">\n'
        "  <resources>\n"
        '    <object id="1" type="model">\n'
        "      <mesh>\n        <vertices>\n" + vx + "\n        </vertices>\n"
        "        <triangles>\n" + fx + "\n        </triangles>\n"
        "      </mesh>\n    </object>\n  </resources>\n"
        '  <build>\n    <item objectid="1"/>\n  </build>\n</model>\n'
    )
    content_types = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">\n'
        '  <Default Extension="rels" '
        'ContentType="application/vnd.openxmlformats-package.relationships+xml"/>\n'
        '  <Default Extension="model" '
        'ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/>\n'
        "</Types>\n"
    )
    rels = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">\n'
        '  <Relationship Target="/3D/3dmodel.model" Id="rel0" '
        'Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/>\n'
        "</Relationships>\n"
    )
    import io

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, text in (("[Content_Types].xml", content_types), ("_rels/.rels", rels),
                           ("3D/3dmodel.model", model)):
            info = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))  # deterministic
            info.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(info, text)
    return buf.getvalue()


# ---------------------------------------------------------------- labels
CHECKS = ("parse", "units", "watertight", "fits", "walls", "overhangs", "loose_parts")
ALL_PASS = dict.fromkeys(CHECKS, "pass")
PARSE_FAIL = {"parse": "fail", **{c: "skip" for c in CHECKS[1:]}}


def exp(**over: str) -> dict[str, str]:
    e = dict(ALL_PASS)
    e.update(over)
    return e


def overall(e: dict[str, str]) -> str:
    vals = set(e.values())
    return "fail" if "fail" in vals else "warn" if "warn" in vals else "pass"


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, object]] = []

    def add(i: int, ext: str, data: bytes, process: str, kind: str, desc: str,
            e: dict[str, str], size: list[float] | None) -> None:
        bid = f"b{i:02d}"
        (OUT / f"{bid}.{ext}").write_bytes(data)
        split = "dev" if i <= 12 else "held_out"
        rows.append({"id": bid, "file": f"models/{bid}.{ext}", "split": split,
                     "process": process, "kind": kind, "description": desc, "expected": e,
                     "overall": overall(e), "size_mm": size})

    def closed(tris: list[Tri]) -> list[Tri]:
        assert signed_volume(tris) > 0, "valid closed mesh must wind outwards"
        return tris

    # ---------------- dev
    cube40 = closed(box(0, 0, 0, 40, 40, 40))
    add(1, "stl", binary_stl(cube40), "fdm", "valid", "40 mm cube", exp(), [40, 40, 40])

    cnc_max = closed(box(0, 0, 0, 400, 300, 150))
    add(2, "stl", ascii_stl(cnc_max, "b02"), "cnc", "valid",
        "block exactly the cnc build volume 400 x 300 x 150 (equal fits); overhangs skip for cnc",
        exp(overhangs="skip"), [400, 300, 150])

    add(3, "3mf", threemf(closed(box(0, 0, 0, 100, 60, 20))), "resin", "valid",
        "100 x 60 x 20 block, fits the resin printer", exp(), [100, 60, 20])

    add(4, "stl", binary_stl(closed(box(0, 0, 0, 380, 40, 40))), "fdm", "valid",
        "380 x 40 x 40 bar: too long for x, fits the 350 x 350 x 400 printer only after rotation"
        " (sorted sides)", exp(), [380, 40, 40])

    # top face is the side quad of profile edge (40,40)->(0,40): indices 8+2, 8+3
    top_idx = 4 * 2 + 2
    open_cube = [t for k, t in enumerate(cube40) if k != top_idx]
    add(5, "stl", binary_stl(open_cube), "fdm", "broken",
        "40 mm cube with one top triangle missing (open mesh)",
        exp(watertight="fail", walls="skip"), [40, 40, 40])

    flipped = [flip(t) if k == top_idx else t for k, t in enumerate(cube40)]
    add(6, "stl", ascii_stl(flipped, "b06"), "fdm", "broken",
        "40 mm cube with one top triangle flipped; the flipped face points down, 8.3 % of"
        " surface (under 10 %)", exp(watertight="fail", walls="skip"), [40, 40, 40])
    assert abs(overhang_share(flipped, -0.707) - 800 / 9600) < 1e-6

    add(7, "3mf", threemf(closed(box(0, 0, 0, 10, 3, 3)), unit="inch"), "resin", "broken",
        "3MF unit=inch, 10 x 3 x 3 in = 254 x 76.2 x 76.2 mm; 254 exceeds every resin side (235)",
        exp(fits="fail"), [254, 76.2, 76.2])

    full = binary_stl(cube40)
    add(8, "stl", full[: 84 + 5 * 50 + 20], "fdm", "broken",
        "binary STL truncated: header says 12 triangles, file holds 5.4", PARSE_FAIL, None)

    add(9, "stl", binary_stl(closed(box(0, 0, 0, 40, 40, 0.81))), "fdm", "borderline",
        "40 x 40 x 0.81 mm plate: just above the fdm fail figure 0.8, below warn 1.0",
        exp(walls="warn"), [40, 40, 0.81])

    add(10, "stl", ascii_stl(closed(box(0, 0, 0, 40, 40, 0.79)), "b10"), "fdm", "borderline",
        "40 x 40 x 0.79 mm plate: just below the fdm fail figure 0.8",
        exp(walls="fail"), [40, 40, 0.79])

    t40 = closed(t_shape(40))
    assert abs(overhang_share(t40, -0.866) - 400 / 4200) < 1e-6
    add(11, "3mf", threemf(t40), "resin", "borderline",
        "T shape (stem 10 x 20, bar 20 x 5), 40 mm long: flat bar underside 9.5 % of surface"
        " (400 of 4200 mm2), just under 10 %", exp(), [20, 40, 25])

    add(12, "stl", ascii_stl(closed(box(0, 0, 0, 401, 30, 30)), "b12"), "fdm", "borderline",
        "401 x 30 x 30 bar: 1 mm longer than the tallest fdm side (400)",
        exp(fits="fail"), [401, 30, 30])

    # ---------------- held_out
    add(13, "3mf", threemf(closed(box(0, 0, 0, 5, 4, 3)), unit="centimeter"), "cnc", "valid",
        "3MF unit=centimeter, 5 x 4 x 3 cm = 50 x 40 x 30 mm block; overhangs skip for cnc",
        exp(overhangs="skip"), [50, 40, 30])

    ch50 = closed(chamfer(50))
    d50 = 20 * math.tan(math.radians(50))
    w50 = 20 + 2 * d50
    assert abs(overhang_share(ch50, -0.707) - 0.2513) < 0.001
    assert overhang_share(ch50, -0.866) == 0.0
    add(14, "stl", ascii_stl(ch50, "b14"), "resin", "valid",
        "50 deg chamfered underside (25 % of surface); resin only counts beyond 60 deg, so 0 %",
        exp(), [round(w50, 3), 40, 30])

    ch40 = closed(chamfer(40))
    w40 = 20 + 2 * 20 * math.tan(math.radians(40))
    assert overhang_share(ch40, -0.707) == 0.0
    add(15, "stl", binary_stl(ch40), "fdm", "valid",
        "40 deg chamfered underside (25 % of surface) is within the fdm 45 deg limit, so 0 %",
        exp(), [round(w40, 3), 40, 30])

    inner = [flip(t) for t in box(0.9, 0.9, 0.9, 39.1, 39.1, 39.1)]
    hollow = closed(box(0, 0, 0, 40, 40, 40)) + inner
    assert signed_volume(inner) < 0
    assert abs(overhang_share(hollow, -0.707) - 38.2**2 / (9600 + 6 * 38.2**2)) < 1e-6
    add(16, "stl", ascii_stl(hollow, "b16"), "fdm", "borderline",
        "hollow 40 mm box, 0.9 mm shell (closed outer, reversed inner): wall warn; outer and"
        " inner shells share no vertex; cavity ceiling 7.9 % of surface",
        exp(walls="warn", loose_parts="warn"), [40, 40, 40])

    fin = ((0.0, 0.0, 40.0), (40.0, 0.0, 40.0), (20.0, 0.0, 60.0))
    add(17, "stl", ascii_stl(cube40 + [fin], "b17"), "fdm", "broken",
        "40 mm cube with a vertical fin triangle on a top edge: that edge has three triangles",
        exp(watertight="fail", walls="skip"), [40, 40, 60])

    add(18, "3mf", threemf(closed(box(0, 0, 0, 30, 30, 30)), doctype=True), "fdm", "broken",
        "valid 30 mm cube, but the model XML contains a <!DOCTYPE> (refused)", PARSE_FAIL, None)

    add(19, "stl", binary_stl(closed(box(0, 0, 0, 130, 130, 130))), "resin", "broken",
        "130 mm cube: fits fdm, but two resin sides are 123 and 218, so it fits no resin printer",
        exp(fits="fail"), [130, 130, 130])

    add(20, "3mf", threemf(closed(box(0, 0, 0, 30, 30, 30)), duplicate_index=2), "fdm", "broken",
        "30 mm cube with one side triangle listed twice (duplicate face)",
        exp(watertight="fail", walls="skip"), [30, 30, 30])

    inside_out = [flip(t) for t in box(0, 0, 0, 10, 10, 80)]
    assert signed_volume(inside_out) < 0
    add(21, "stl", binary_stl(inside_out), "fdm", "borderline",
        "10 x 10 x 80 column, closed and consistent but every face points inwards; end faces"
        " are 2.9 % of surface either way", exp(watertight="warn"), [10, 10, 80])

    assert abs(overhang_share(ch50, -0.707) - 0.2513) < 0.001
    add(22, "stl", binary_stl(ch50), "fdm", "borderline",
        "same 50 deg chamfer as b14 but fdm: underside beyond 45 deg is 25 % of surface",
        exp(overhangs="warn"), [round(w50, 3), 40, 30])

    t80 = closed(t_shape(80))
    assert abs(overhang_share(t80, -0.866) - 800 / 7800) < 1e-6
    add(23, "stl", ascii_stl(t80, "b23"), "resin", "borderline",
        "T shape as b11 but 80 mm long: bar underside 10.3 % of surface (800 of 7800 mm2),"
        " just over 10 %", exp(overhangs="warn"), [20, 80, 25])

    debris = closed(box(35, 0, 0, 35.5, 0.5, 0.5))
    add(24, "3mf", threemf(closed(box(0, 0, 0, 30, 30, 30)) + debris), "fdm", "borderline",
        "30 mm cube plus a 0.5 mm debris cube 5 mm away (second shell); debris surface 1.5 mm2"
        " is under the 4 mm2 thin-wall minimum", exp(loose_parts="warn"), [35.5, 30, 30])

    assert len(rows) == 24
    with (HERE / "labels.jsonl").open("w", encoding="utf-8", newline="\n") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")
    print(f"wrote {len(rows)} models and labels.jsonl")


if __name__ == "__main__":
    main()
