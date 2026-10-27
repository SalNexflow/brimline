"""Read STL (binary or text) and 3MF into one triangle mesh in millimetres.

Our own small reader instead of a mesh library (D98): both formats are short to read, and every
refusal can say in plain words what is wrong with the file. Nothing here judges the part; it only
reads it, refusing anything it cannot read safely."""

import io
import re
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass

import numpy as np
import numpy.typing as npt

from brimline_engine.files.config import Limits

Floats = npt.NDArray[np.float64]
Ints = npt.NDArray[np.int64]

# 3MF units and their size in mm (3MF core specification, "unit" attribute).
UNITS_MM = {
    "micron": 0.001,
    "millimeter": 1.0,
    "centimeter": 10.0,
    "inch": 25.4,
    "foot": 304.8,
    "meter": 1000.0,
}
# Vertices closer than this (mm) are the same vertex: STL repeats every corner per triangle.
WELD_MM = 1e-4

STL_RECORD = np.dtype([("normal", "<f4", (3,)), ("v", "<f4", (9,)), ("attr", "<u2")])
NUMBER = r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?"
VERTEX = re.compile(rf"\bvertex\s+({NUMBER})\s+({NUMBER})\s+({NUMBER})")
FACET = re.compile(r"\bfacet\b")


class ParseError(Exception):
    """The file cannot be read as a mesh. The message is shown to the customer as is."""


@dataclass(frozen=True)
class Mesh:
    vertices: Floats  # (n, 3) in mm, welded
    faces: Ints  # (m, 3) vertex indices, in the file's winding order
    file_format: str  # "stl-binary", "stl-text" or "3mf"
    unit: str  # what the file's numbers were read as
    dropped_faces: int  # triangles with two equal corners after welding (no area, no edges)


def read_mesh(data: bytes, filename: str, limits: Limits, unit: str = "millimeter") -> Mesh:
    """`unit` is what STL numbers mean (STL has no unit; staff choose it). A 3MF says its own."""
    if not data:
        raise ParseError("the file is empty")
    if len(data) > limits.max_upload_bytes:
        raise ParseError(f"the file is larger than {limits.max_upload_bytes // 1_048_576} MiB")
    if unit not in UNITS_MM:
        raise ParseError(f"unknown unit {unit!r}")
    name = filename.lower()
    if name.endswith(".3mf"):
        triangles, unit = _read_3mf(data, limits)
        fmt = "3mf"
    elif name.endswith(".stl"):
        triangles, fmt = _read_stl(data, limits)
    else:
        raise ParseError("only STL and 3MF files can be checked")
    if len(triangles) == 0:
        raise ParseError("the file holds no triangles")
    if not np.isfinite(triangles).all():
        raise ParseError("the file holds coordinates that are not numbers (NaN or infinity)")
    return _weld(triangles * UNITS_MM[unit], fmt, unit)


def _read_stl(data: bytes, limits: Limits) -> tuple[Floats, str]:
    # A binary STL is an 80-byte header, a triangle count, then 50 bytes per triangle. Text STL
    # often starts with "solid" too, so the length is the reliable test.
    if len(data) >= 84:
        count = int.from_bytes(data[80:84], "little")
        if 84 + 50 * count == len(data):
            if count > limits.max_triangles:
                raise ParseError(_too_many(count, limits))
            records = np.frombuffer(data, dtype=STL_RECORD, count=count, offset=84)
            return records["v"].astype(np.float64).reshape(count, 3, 3), "stl-binary"
    if data.lstrip()[:5].lower() != b"solid":
        if len(data) >= 84:
            raise ParseError(
                "this is not a readable STL: as binary STL its length does not match its"
                " triangle count (truncated or damaged), and it is not text STL"
            )
        raise ParseError("this is not an STL file (too short, and not text STL)")
    try:
        text = data.decode("ascii")
    except UnicodeDecodeError as e:
        raise ParseError("this text STL holds characters that are not plain text") from e
    numbers = VERTEX.findall(text)
    if len(numbers) % 3 != 0 or len(numbers) // 3 != len(FACET.findall(text)):
        # Each "facet normal ... endfacet" block has three vertices ("endfacet" does not match).
        raise ParseError("this text STL is damaged: its facets do not each have three vertices")
    if len(numbers) // 3 > limits.max_triangles:
        raise ParseError(_too_many(len(numbers) // 3, limits))
    return np.array(numbers, dtype=np.float64).reshape(-1, 3, 3), "stl-text"


def _read_3mf(data: bytes, limits: Limits) -> tuple[Floats, str]:
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as e:
        raise ParseError("this 3MF is not a readable zip archive") from e
    with archive:
        names = set(archive.namelist())
        path = _model_path(archive, names, limits)
        xml = _read_member(archive, path, limits)
    # The standard library parser does not fetch external entities, but nested entities can
    # still blow up in memory. A 3MF model never needs a DOCTYPE, so any is refused.
    if b"<!DOCTYPE" in xml or b"<!ENTITY" in xml:
        raise ParseError("this 3MF contains a DOCTYPE or ENTITY declaration, which is refused")
    try:
        root = ET.fromstring(xml)
    except ET.ParseError as e:
        raise ParseError(f"this 3MF's model is not valid XML ({e})") from e
    unit = root.get("unit", "millimeter")
    if unit not in UNITS_MM:
        raise ParseError(f"this 3MF uses an unknown unit {unit!r}")
    objects = {o.get("id"): o for o in _all(root, "object")}
    items = [i for i in _all(root, "item")]
    parts: list[Floats] = []
    identity = np.eye(4)
    if items:
        for item in items:
            _object_triangles(objects, item.get("objectid"), _transform(item), parts, limits, 0)
    else:  # no build section: take every mesh as placed
        for oid, obj in objects.items():
            if _first(obj, "mesh") is not None:
                _object_triangles(objects, oid, identity, parts, limits, 0)
    if not parts:
        raise ParseError("this 3MF has no mesh to print")
    return np.concatenate(parts), unit


def _model_path(archive: zipfile.ZipFile, names: set[str], limits: Limits) -> str:
    """The 3D model part named in _rels/.rels, or the usual 3D/3dmodel.model."""
    if "_rels/.rels" in names:
        try:
            rels = ET.fromstring(_read_member(archive, "_rels/.rels", limits))
        except ET.ParseError as e:
            raise ParseError("this 3MF's _rels/.rels is not valid XML") from e
        for rel in _all(rels, "Relationship"):
            if rel.get("Type", "").endswith("/3dmodel"):
                target = rel.get("Target", "").lstrip("/")
                if target in names:
                    return target
    if "3D/3dmodel.model" in names:
        return "3D/3dmodel.model"
    raise ParseError("this 3MF has no 3D model part")


def _read_member(archive: zipfile.ZipFile, name: str, limits: Limits) -> bytes:
    # The size in the zip header can lie, so read in chunks and stop at the limit (zip bombs).
    out = bytearray()
    with archive.open(name) as f:
        while chunk := f.read(1 << 20):
            out += chunk
            if len(out) > limits.max_unzipped_bytes:
                raise ParseError(
                    f"this 3MF unpacks to more than {limits.max_unzipped_bytes // 1_048_576} MiB"
                )
    return bytes(out)


def _object_triangles(
    objects: dict[str | None, ET.Element],
    oid: str | None,
    matrix: Floats,
    out: list[Floats],
    limits: Limits,
    depth: int,
) -> None:
    if depth > 8:
        raise ParseError("this 3MF nests components too deeply (or in a loop)")
    obj = objects.get(oid)
    if obj is None:
        raise ParseError(f"this 3MF refers to an object {oid!r} it does not define")
    mesh = _first(obj, "mesh")
    if mesh is not None:
        vertices = np.array(
            [[float(v.get(a, "nan")) for a in ("x", "y", "z")] for v in _all(mesh, "vertex")],
            dtype=np.float64,
        ).reshape(-1, 3)
        try:
            index = np.array(
                [[int(t.get(a, "-1")) for a in ("v1", "v2", "v3")] for t in _all(mesh, "triangle")],
                dtype=np.int64,
            ).reshape(-1, 3)
        except ValueError as e:
            raise ParseError("this 3MF has a triangle with a corner that is not a number") from e
        if sum(len(p) for p in out) + len(index) > limits.max_triangles:
            raise ParseError(_too_many(sum(len(p) for p in out) + len(index), limits))
        if len(index) and (index.min() < 0 or index.max() >= len(vertices)):
            raise ParseError("this 3MF has a triangle pointing at a vertex that does not exist")
        out.append(_apply(matrix, vertices)[index])
    for comp in _all(obj, "component"):
        _object_triangles(
            objects, comp.get("objectid"), _transform(comp) @ matrix, out, limits, depth + 1
        )


def _transform(el: ET.Element) -> Floats:
    """3MF writes a 3x4 matrix as 12 numbers for row vectors: p' = [x y z 1] @ M."""
    text = el.get("transform")
    m = np.eye(4)
    if text:
        try:
            values = [float(x) for x in text.split()]
        except ValueError as e:
            raise ParseError("this 3MF has a transform that is not numbers") from e
        if len(values) != 12:
            raise ParseError("this 3MF has a transform without 12 numbers")
        m[:, :3] = np.array(values).reshape(4, 3)
    return m


def _apply(matrix: Floats, points: Floats) -> Floats:
    ones = np.ones((len(points), 1))
    result: Floats = (np.hstack([points, ones]) @ matrix)[:, :3]
    return result


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _all(el: ET.Element, name: str) -> list[ET.Element]:
    return [e for e in el.iter() if _local(e.tag) == name]


def _first(el: ET.Element, name: str) -> ET.Element | None:
    return next((e for e in el if _local(e.tag) == name), None)


def _too_many(count: int, limits: Limits) -> str:
    return f"the file has {count:,} triangles; the checker reads at most {limits.max_triangles:,}"


def _weld(triangles: Floats, fmt: str, unit: str) -> Mesh:
    corners = triangles.reshape(-1, 3)
    keys = np.round(corners / WELD_MM).astype(np.int64)
    unique, first, inverse = np.unique(keys, axis=0, return_index=True, return_inverse=True)
    del unique
    faces = inverse.reshape(-1, 3).astype(np.int64)
    keep = (
        (faces[:, 0] != faces[:, 1]) & (faces[:, 1] != faces[:, 2]) & (faces[:, 0] != faces[:, 2])
    )
    return Mesh(
        vertices=corners[first],
        faces=faces[keep],
        file_format=fmt,
        unit=unit,
        dropped_faces=int((~keep).sum()),
    )
