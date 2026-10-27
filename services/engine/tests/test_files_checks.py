"""The file checker (M7) on shapes whose answers are known by hand: a 40 mm cube has volume
64,000 mm³ and surface 9,600 mm²; a plate's wall is its thickness; the T shape's underside is
800 of 5,200 mm². Expected values come from geometry, not from the checker's output."""

import io
import math
import zipfile

import numpy as np
import pytest

from brimline_engine.files import measure
from brimline_engine.files import samples as s
from brimline_engine.files.checks import check_file, planning_values
from brimline_engine.files.config import files_config
from brimline_engine.files.mesh import Floats, Mesh, ParseError, read_mesh
from brimline_engine.shop_config import Process, load_shop_config

CFG = files_config()
MACHINES = load_shop_config().machines
CUBE = s.box(40, 40, 40)
T_PROFILE = [(0, 0), (10, 0), (10, 30), (30, 30), (30, 40), (-20, 40), (-20, 30), (0, 30)]


def report(
    data: bytes, name: str = "part.stl", process: Process | None = "fdm", unit: str = "millimeter"
) -> dict[str, str]:
    r = check_file(data, name, process, MACHINES, CFG, unit)
    return {c.name: c.status for c in r.checks}


def mesh(tris: Floats) -> Mesh:
    return read_mesh(s.binary_stl(tris), "p.stl", CFG.limits)


def test_a_cube_is_measured_exactly_in_every_format() -> None:
    for data, name in [
        (s.binary_stl(CUBE), "c.stl"),
        (s.text_stl(CUBE), "c.stl"),
        (s.three_mf(CUBE), "c.3mf"),
    ]:
        r = check_file(data, name, "fdm", MACHINES, CFG)
        assert r.overall == "pass", r.checks
        m = r.measurements
        assert m is not None
        assert m.size_mm == pytest.approx((40, 40, 40))
        assert m.volume_mm3 == pytest.approx(64_000)
        assert m.surface_mm2 == pytest.approx(9_600)
        assert m.shells == 1 and m.triangles == 12


def test_corners_repeated_per_triangle_are_welded() -> None:
    m = mesh(CUBE)
    assert len(m.vertices) == 8 and measure.edges(m).closed


@pytest.mark.parametrize(
    ("thickness", "process", "expected"),
    [
        (0.6, "fdm", "fail"),  # under 0.8
        (0.79, "fdm", "fail"),
        (0.81, "fdm", "warn"),  # 0.8 to 1.0
        (1.0, "fdm", "pass"),  # exactly the warn figure is not "thinner than"
        (0.39, "resin", "fail"),
        (0.5, "resin", "warn"),
        (0.7, "resin", "pass"),
        (0.45, "cnc", "fail"),
        (0.6, "cnc", "warn"),
    ],
)
def test_plate_walls_against_each_process_limit(
    thickness: float, process: Process, expected: str
) -> None:
    assert report(s.binary_stl(s.box(60, 60, thickness)), process=process)["walls"] == expected


def test_a_plate_wall_is_its_thickness() -> None:
    w = measure.walls(mesh(s.box(60, 60, 0.6)), [0.8, 1.0], 4000, 10**8, 1.0)
    assert w.thinnest_mm == pytest.approx(0.6)
    # Both big faces (2 x 3600 mm²) are thinner than 0.8; the 0.6 mm rim faces are not.
    assert w.thin_area_mm2[0.8] == pytest.approx(7200)


def test_a_tiny_thin_patch_is_ignored_but_a_large_one_is_not() -> None:
    # 1.5 x 1.5 x 0.5 mm: top and bottom are 2 x 2.25 = 4.5 mm² thinner than 0.8: over 4 mm².
    assert report(s.binary_stl(s.box(1.5, 1.5, 0.5)))["walls"] == "fail"
    # 1 x 1 x 0.5 mm: only 2 mm² of top and bottom (the rim is 1 mm across): under 4 mm².
    assert report(s.binary_stl(s.box(1, 1, 0.5)))["walls"] == "pass"


def test_a_hollow_box_wall_is_the_shell_thickness() -> None:
    r = check_file(s.binary_stl(s.hollow_box(50, 50, 50, 0.5)), "h.stl", "resin", MACHINES, CFG)
    statuses = {c.name: c.status for c in r.checks}
    assert statuses["walls"] == "warn" and statuses["loose_parts"] == "warn"
    assert r.measurements is not None
    assert r.measurements.volume_mm3 == pytest.approx(50**3 - 49**3)
    assert r.measurements.thinnest_wall_mm == pytest.approx(0.5)


def test_open_flipped_and_non_manifold_surfaces() -> None:
    open_cube = mesh(CUBE[1:])
    assert measure.edges(open_cube).boundary == 3
    flipped_one = CUBE.copy()
    flipped_one[0] = flipped_one[0][[0, 2, 1]]
    assert measure.edges(mesh(flipped_one)).same_direction == 3
    fin = np.array([[[0, 0, 40], [40, 0, 40], [20, 0, 60]]], dtype=np.float64)
    assert measure.edges(mesh(np.concatenate([CUBE, fin]))).non_manifold == 1
    for tris in (CUBE[1:], flipped_one):
        statuses = report(s.binary_stl(tris))
        assert statuses["watertight"] == "fail" and statuses["walls"] == "skip"


def test_inside_out_is_a_warning_and_volume_stays_positive() -> None:
    r = check_file(s.binary_stl(s.flip(CUBE)), "c.stl", "fdm", MACHINES, CFG)
    assert {c.name: c.status for c in r.checks}["watertight"] == "warn"
    assert r.measurements is not None and r.measurements.volume_mm3 == pytest.approx(64_000)
    assert r.measurements.overhang_share == 0  # the flipped bottom is still read as the bed


def test_overhang_share_of_the_t_shape() -> None:
    t = mesh(s.extrude(T_PROFILE, 20))
    assert measure.surface_mm2(t) == pytest.approx(5200)
    assert measure.overhang_share(t, 45, 1.0) == pytest.approx(800 / 5200)


def test_a_50_degree_underside_needs_support_on_fdm_but_not_on_resin() -> None:
    run = 10 * math.tan(math.radians(50))  # 50° from vertical over a 10 mm rise
    chamfer = mesh(s.extrude([(0, 0), (10, 0), (10 + run, 10), (10 + run, 20), (0, 20)], 20))
    assert measure.overhang_share(chamfer, 45, 1.0) > 0
    assert measure.overhang_share(chamfer, 60, 1.0) == 0
    assert report(s.binary_stl(s.box(20, 20, 20)), process="cnc")["overhangs"] == "skip"


def test_loose_parts_count_shells() -> None:
    two = np.concatenate([s.box(10, 10, 10), s.box(10, 10, 10, (20, 0, 0))])
    assert int(measure.shells(mesh(two)).max()) + 1 == 2
    assert report(s.binary_stl(two))["loose_parts"] == "warn"


def test_fits_turns_the_part_and_equal_counts_as_fitting() -> None:
    assert (
        report(s.binary_stl(s.box(20, 20, 400)))["fits"] == "pass"
    )  # only the large printer, standing
    assert report(s.binary_stl(s.box(400, 20, 20)))["fits"] == "pass"  # same, lying down
    assert report(s.binary_stl(s.box(401, 20, 20)))["fits"] == "fail"
    assert report(s.binary_stl(s.box(130, 130, 130)), process="resin")["fits"] == "fail"
    assert report(s.binary_stl(CUBE), process=None)["fits"] == "skip"


def test_units_from_3mf_from_staff_and_the_scale_warning() -> None:
    inch = check_file(s.three_mf(s.box(1, 2, 3), unit="inch"), "i.3mf", "fdm", MACHINES, CFG)
    assert inch.measurements is not None
    assert inch.measurements.size_mm == pytest.approx((25.4, 50.8, 76.2))
    stl_inch = check_file(s.binary_stl(s.box(1, 2, 3)), "i.stl", "fdm", MACHINES, CFG, "inch")
    assert stl_inch.measurements is not None and stl_inch.measurements.size_mm == pytest.approx(
        (25.4, 50.8, 76.2)
    )
    assert report(s.binary_stl(s.box(0.05, 0.04, 0.03)))["units"] == "warn"  # saved in metres
    assert report(s.three_mf(s.box(2.5, 2, 2), unit="meter"), "m.3mf")["units"] == "warn"  # 2.5 m


def test_3mf_build_transform_is_applied() -> None:
    # Row-vector 3MF matrix: scale x by 2, then move 100 mm along x.
    data = s.three_mf(s.box(10, 10, 10), transform="2 0 0 0 1 0 0 0 1 100 0 0")
    m = read_mesh(data, "t.3mf", CFG.limits)
    assert measure.size_mm(m) == pytest.approx((20, 10, 10))
    assert m.vertices[:, 0].min() == pytest.approx(100)


@pytest.mark.parametrize(
    ("data", "name", "words"),
    [
        (b"", "a.stl", "empty"),
        (s.binary_stl(CUBE)[:-7], "a.stl", "truncated"),
        (b"just some text\n", "a.stl", "not an STL"),
        (
            b"solid x\nfacet normal 0 0 1\n outer loop\n vertex 0 0 0\n vertex 1 0 0\n endloop\nendfacet\nendsolid",
            "a.stl",
            "three vertices",
        ),
        (s.three_mf(CUBE, doctype=True), "a.3mf", "DOCTYPE"),
        (b"PK not really a zip", "a.3mf", "not a readable zip"),
        (s.binary_stl(CUBE), "a.obj", "only STL and 3MF"),
        (s.three_mf(s.box(1, 1, 1), unit="furlong"), "a.3mf", "unknown unit"),
    ],
)
def test_unreadable_files_are_refused_with_a_reason(data: bytes, name: str, words: str) -> None:
    r = check_file(data, name, "fdm", MACHINES, CFG)
    assert r.overall == "fail" and r.measurements is None
    parse = r.checks[0]
    assert parse.name == "parse" and parse.status == "fail" and words in parse.reason
    assert all(c.status == "skip" for c in r.checks[1:])


def test_limits_stop_huge_files_and_zip_bombs() -> None:
    small = CFG.limits.model_copy(update={"max_triangles": 11, "max_unzipped_bytes": 2000})
    with pytest.raises(ParseError, match="at most 11"):
        read_mesh(s.binary_stl(CUBE), "a.stl", small)
    bomb = io.BytesIO()
    with zipfile.ZipFile(bomb, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("3D/3dmodel.model", b"<model>" + b" " * 50_000 + b"</model>")
    with pytest.raises(ParseError, match="unpacks to more than"):
        read_mesh(bomb.getvalue(), "a.3mf", small)


def test_bad_numbers_are_refused() -> None:
    nan = CUBE.copy()
    nan[0, 0, 0] = np.nan
    with pytest.raises(ParseError, match="not numbers"):
        read_mesh(s.binary_stl(nan), "a.stl", CFG.limits)


def test_planning_values_from_a_cube() -> None:
    # PLA: 64 cm³ x 1.24 g/cm³ x 0.5 fill = 39.68 g -> 40 g; 32,000 mm³ / 300 mm³ per min -> 107 min.
    r = check_file(s.binary_stl(CUBE), "c.stl", "fdm", MACHINES, CFG)
    v = planning_values(r, "PLA-BLACK", "fdm", CFG)
    assert (v.part_mm, v.grams_per_part, v.minutes_per_part) == ((40, 40, 40), 40, 107)
    # Resin, 30 mm tall: 27 cm³ x 1.15 = 31.05 -> 31 g; 600 layers x 9 s = 90 min.
    r = check_file(s.binary_stl(s.box(30, 30, 30)), "c.stl", "resin", MACHINES, CFG)
    v = planning_values(r, "RESIN-GREY", "resin", CFG)
    assert (v.part_mm, v.grams_per_part, v.minutes_per_part) == ((30, 30, 30), 31, 90)
    # CNC: size only; staff enter weight and time.
    r = check_file(s.binary_stl(CUBE), "c.stl", "cnc", MACHINES, CFG)
    v = planning_values(r, "AL-6061", "cnc", CFG)
    assert (v.part_mm, v.grams_per_part, v.minutes_per_part) == ((40, 40, 40), None, None)


def test_planning_values_round_size_up_and_hold_back_what_is_unsure() -> None:
    inch = check_file(s.three_mf(s.box(1.5, 1.5, 1.5), unit="inch"), "c.3mf", "fdm", MACHINES, CFG)
    assert planning_values(inch, "PLA-BLACK", "fdm", CFG).part_mm == (39, 39, 39)  # 38.1 up
    tiny = check_file(s.binary_stl(s.box(0.04, 0.04, 0.04)), "c.stl", "fdm", MACHINES, CFG)
    assert planning_values(tiny, "PLA-BLACK", "fdm", CFG).part_mm is None
    assert planning_values(tiny, "PLA-BLACK", "fdm", CFG, units_confirmed=True).part_mm == (1, 1, 1)
    open_cube = check_file(s.binary_stl(CUBE[1:]), "c.stl", "fdm", MACHINES, CFG)
    v = planning_values(open_cube, "PLA-BLACK", "fdm", CFG)
    assert v.part_mm == (40, 40, 40) and v.grams_per_part is None and v.minutes_per_part is None


def test_a_big_mesh_is_sampled_and_still_finds_thin_walls() -> None:
    plates = np.concatenate(
        [s.box(5, 5, 0.5, (i * 8, j * 8, 0)) for i in range(25) for j in range(25)]
    )
    assert len(plates) > CFG.limits.wall_rays
    w = measure.walls(
        mesh(plates), [0.8, 1.0], CFG.limits.wall_rays, CFG.limits.wall_ray_tests, 1.0
    )
    assert w.sampled < len(plates)
    # 625 plates x 50 mm² of thin top and bottom = 31,250 mm²; the estimate is within 15 %.
    assert w.thin_area_mm2[0.8] == pytest.approx(31_250, rel=0.15)


def test_the_checker_does_not_import_any_model_code() -> None:
    # Vision advice can never be a pass/fail input: the modules that read, measure and judge a
    # file cannot even reach the AI package (directly or through another Brimline module).
    import ast
    from pathlib import Path

    folder = Path(__file__).parents[1] / "src" / "brimline_engine" / "files"
    allowed = {"brimline_engine.files", "brimline_engine.settings", "brimline_engine.shop_config"}
    for name in ("mesh.py", "measure.py", "checks.py", "config.py"):
        tree = ast.parse((folder / name).read_text(encoding="utf-8"))
        names = [a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names]
        names += [n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)]
        ours = [n for n in names if n.startswith("brimline_engine")]
        assert all(any(n == a or n.startswith(a + ".") for a in allowed) for n in ours), (name, ours)
