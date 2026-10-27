"""The file report: each check is pass, warn, fail or skip with a plain reason, decided by code
from measurements and the thresholds in config/files.toml. No model takes part (hard rule 1);
vision advice, when on, is stored apart and never read here."""

import math
from collections.abc import Sequence
from typing import Literal

from pydantic import BaseModel

from brimline_engine.files import measure
from brimline_engine.files.config import FilesConfig
from brimline_engine.files.mesh import Mesh, ParseError, read_mesh
from brimline_engine.shop_config import Machine, Process

Status = Literal["pass", "warn", "fail", "skip"]
CHECKS = ("parse", "units", "watertight", "fits", "walls", "overhangs", "loose_parts")


class CheckResult(BaseModel):
    name: str
    status: Status
    reason: str


class Measurements(BaseModel):
    file_format: str
    unit: str
    triangles: int
    size_mm: tuple[float, float, float]
    volume_mm3: float | None  # only for a closed surface
    surface_mm2: float
    shells: int
    thinnest_wall_mm: float | None
    overhang_share: float | None
    fits_on: list[str]


class Report(BaseModel):
    checks: list[CheckResult]
    overall: Literal["pass", "warn", "fail"]
    measurements: Measurements | None

    def status(self, name: str) -> Status:
        return next(c.status for c in self.checks if c.name == name)


def overall(checks: Sequence[CheckResult]) -> Literal["pass", "warn", "fail"]:
    statuses = {c.status for c in checks}
    return "fail" if "fail" in statuses else "warn" if "warn" in statuses else "pass"


def check_file(
    data: bytes,
    filename: str,
    process: Process | None,
    machines: Sequence[Machine],
    cfg: FilesConfig,
    unit: str = "millimeter",
) -> Report:
    try:
        mesh = read_mesh(data, filename, cfg.limits, unit)
    except ParseError as e:
        checks = [CheckResult(name="parse", status="fail", reason=str(e))]
        checks += [
            CheckResult(name=n, status="skip", reason="the file could not be read")
            for n in CHECKS[1:]
        ]
        return Report(checks=checks, overall="fail", measurements=None)
    return _check_mesh(mesh, process, machines, cfg)


def _check_mesh(
    mesh: Mesh, process: Process | None, machines: Sequence[Machine], cfg: FilesConfig
) -> Report:
    checks: list[CheckResult] = []

    def add(name: str, status: Status, reason: str) -> None:
        checks.append(CheckResult(name=name, status=status, reason=reason))

    if len(mesh.faces) == 0:
        add("parse", "fail", "every triangle has two equal corners: there is no surface")
        for n in CHECKS[1:]:
            add(n, "skip", "the file has no surface")
        return Report(checks=checks, overall="fail", measurements=None)
    dropped = f" ({mesh.dropped_faces} zero-area triangles ignored)" if mesh.dropped_faces else ""
    add("parse", "pass", f"{len(mesh.faces):,} triangles read from {mesh.file_format}{dropped}")

    size = measure.size_mm(mesh)
    largest = max(size)
    dims = " x ".join(f"{s:.2f}" for s in size)
    if largest < cfg.scale.smallest_plausible_mm:
        add("units", "warn", f"only {dims} mm: was the file saved in inches, cm or metres?")
    elif largest > cfg.scale.largest_plausible_mm:
        add("units", "warn", f"{dims} mm is larger than anything the shop makes: wrong unit?")
    else:
        add("units", "pass", f"{dims} mm, read as {mesh.unit}")

    e = measure.edges(mesh)
    signed = measure.signed_volume_mm3(mesh)
    outward = -1.0 if e.closed and signed < 0 else 1.0
    if not e.closed:
        problems = [
            f"{e.boundary} open edges (holes)" if e.boundary else "",
            f"{e.non_manifold} edges shared by three or more triangles" if e.non_manifold else "",
            f"{e.same_direction} edges where a neighbouring triangle is flipped"
            if e.same_direction
            else "",
        ]
        add("watertight", "fail", "not a closed surface: " + ", ".join(p for p in problems if p))
    elif signed < 0:
        add("watertight", "warn", "closed, but inside out: every face points inwards")
    elif signed == 0:
        add("watertight", "fail", "closed, but encloses no volume")
    else:
        add("watertight", "pass", f"closed surface, {signed / 1000:.2f} cm³")
    closed = e.closed and signed != 0

    fits_on = [m.code for m in machines if _fits(size, m.build_mm)]
    if process is None:
        add("fits", "skip", "no material chosen yet, so no process to compare with")
    else:
        same = [m for m in machines if m.process == process]
        ok = [m.code for m in same if m.code in fits_on]
        if ok:
            add("fits", "pass", f"fits {', '.join(ok)} (turned if needed)")
        else:
            biggest = max(same, key=lambda m: sorted(m.build_mm), default=None)
            room = " x ".join(map(str, biggest.build_mm)) if biggest else "none"
            add("fits", "fail", f"{dims} mm fits no {process} machine (largest {room} mm)")

    walls = None
    if process is None:
        add("walls", "skip", "no material chosen yet, so no wall limits")
    elif not closed:
        add("walls", "skip", "wall thickness needs a closed surface")
    else:
        lim = getattr(cfg.walls, process)
        walls = measure.walls(
            mesh,
            [lim.fail_mm, lim.warn_mm],
            cfg.limits.wall_rays,
            cfg.limits.wall_ray_tests,
            outward,
        )
        area = cfg.walls.min_thin_area_mm2
        thin = (
            f"thinnest wall about {walls.thinnest_mm:.2f} mm"
            if walls.thinnest_mm is not None
            else f"none under {lim.warn_mm} mm found"
        )
        if walls.thin_area_mm2[lim.fail_mm] > area:
            add(
                "walls",
                "fail",
                f"{walls.thin_area_mm2[lim.fail_mm]:.0f} mm² of surface is thinner than {lim.fail_mm} mm ({thin})",
            )
        elif walls.thin_area_mm2[lim.warn_mm] > area:
            add(
                "walls",
                "warn",
                f"{walls.thin_area_mm2[lim.warn_mm]:.0f} mm² of surface is thinner than {lim.warn_mm} mm ({thin})",
            )
        else:
            add(
                "walls",
                "pass",
                f"no wall thinner than {lim.warn_mm} mm over more than {area:g} mm² ({thin})",
            )

    share = None
    if process is None:
        add("overhangs", "skip", "no material chosen yet")
    elif process == "cnc":
        add("overhangs", "skip", "milling has no overhangs")
    else:
        angle = cfg.overhangs.max_from_vertical_deg[process]
        share = measure.overhang_share(mesh, angle, outward)
        text = f"{share:.0%} of the surface faces down more than {angle:g}° from vertical, as saved"
        add(
            "overhangs",
            "warn" if share > cfg.overhangs.warn_share else "pass",
            text + (": needs support" if share > cfg.overhangs.warn_share else ""),
        )

    labels = measure.shells(mesh)
    count = int(labels.max()) + 1
    if count == 1:
        add("loose_parts", "pass", "one connected part")
    else:
        vols = measure.shell_volumes_mm3(mesh, labels)
        debris = sum(v < cfg.loose_parts.debris_mm3 for v in vols)
        tiny = (
            f", {debris} of them tiny (under {cfg.loose_parts.debris_mm3:g} mm³)" if debris else ""
        )
        add("loose_parts", "warn", f"{count} separate pieces{tiny}: intended?")

    return Report(
        checks=checks,
        overall=overall(checks),
        measurements=Measurements(
            file_format=mesh.file_format,
            unit=mesh.unit,
            triangles=len(mesh.faces),
            size_mm=size,
            volume_mm3=abs(signed) if closed else None,
            surface_mm2=measure.surface_mm2(mesh),
            shells=count,
            thinnest_wall_mm=walls.thinnest_mm if walls else None,
            overhang_share=share,
            fits_on=fits_on,
        ),
    )


def _fits(size: tuple[float, float, float], build: tuple[int, int, int]) -> bool:
    # Turned to any axis-aligned orientation, the same rule as the scheduler (durations.fits).
    return all(p <= b + 1e-6 for p, b in zip(sorted(size), sorted(build), strict=True))


# --- What a report fills on a quote line or job ---------------------------------------------------


class PlanningValues(BaseModel):
    """Values code computed from the file, or None with the reason they were not."""

    part_mm: tuple[int, int, int] | None
    grams_per_part: int | None
    minutes_per_part: int | None
    notes: list[str]


def planning_values(
    report: Report,
    material: str | None,
    process: Process | None,
    cfg: FilesConfig,
    *,
    units_confirmed: bool = False,
) -> PlanningValues:
    m = report.measurements
    notes: list[str] = []
    if m is None:
        return PlanningValues(
            part_mm=None,
            grams_per_part=None,
            minutes_per_part=None,
            notes=["the file could not be read"],
        )
    part_mm: tuple[int, int, int] | None = None
    if report.status("units") == "pass" or units_confirmed:
        # Rounded up to whole mm, so a part never looks smaller than it is.
        x, y, z = (max(1, math.ceil(round(s, 2))) for s in m.size_mm)
        part_mm = (x, y, z)
    else:
        notes.append(
            "size not used: the unit looks wrong; confirm it or upload again with the right unit"
        )
    grams = minutes = None
    est = cfg.estimates
    if m.volume_mm3 is None:
        notes.append("grams and print time not estimated: the surface is not closed")
    elif part_mm is None:
        pass
    elif process == "cnc":
        notes.append("CNC: weight and machining time are entered by staff")
    elif process is None or material is None:
        notes.append("grams and print time need a material")
    elif material not in cfg.density_g_per_cm3:
        notes.append(f"no density for {material} in config/files.toml")
    else:
        fill = est.fdm_fill if process == "fdm" else est.resin_fill
        grams = max(1, round(m.volume_mm3 / 1000 * cfg.density_g_per_cm3[material] * fill))
        if process == "fdm":
            minutes = max(
                est.fdm_minimum_minutes, math.ceil(m.volume_mm3 * fill / est.fdm_mm3_per_minute)
            )
        else:
            layers = math.ceil(m.size_mm[2] / est.resin_layer_mm)
            minutes = max(1, math.ceil(layers * est.resin_seconds_per_layer / 60))
        notes.append(
            "grams and minutes are estimates from the file (config/files.toml); staff can change them"
        )
    return PlanningValues(
        part_mm=part_mm, grams_per_part=grams, minutes_per_part=minutes, notes=notes
    )
