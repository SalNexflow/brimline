"""Measurements of a welded mesh: size, closedness, volume, shells, overhangs, wall thickness.

Pure functions on numpy arrays, each testable with shapes whose answer is known by hand (a 40 mm
cube has volume 64,000 mm³; a 0.6 mm plate has 0.6 mm walls)."""

import math
from dataclasses import dataclass

import numpy as np

from brimline_engine.files.mesh import Floats, Ints, Mesh

BED_MM = 0.01  # triangles this close to the lowest point sit on the bed


@dataclass(frozen=True)
class Edges:
    boundary: int  # edges used by one triangle: holes
    non_manifold: int  # edges used by three or more
    same_direction: int  # edges two triangles run the same way: a flipped neighbour

    @property
    def closed(self) -> bool:
        return self.boundary == 0 and self.non_manifold == 0 and self.same_direction == 0


def size_mm(mesh: Mesh) -> tuple[float, float, float]:
    span = np.ptp(mesh.vertices[mesh.faces.reshape(-1)], axis=0) if len(mesh.faces) else np.zeros(3)
    return (float(span[0]), float(span[1]), float(span[2]))


def corners(mesh: Mesh) -> tuple[Floats, Floats, Floats]:
    v = mesh.vertices[mesh.faces]
    return v[:, 0], v[:, 1], v[:, 2]


def face_cross(mesh: Mesh) -> Floats:
    """Cross product per face: its direction follows the winding, its length is twice the area."""
    a, b, c = corners(mesh)
    result: Floats = np.cross(b - a, c - a)
    return result


def surface_mm2(mesh: Mesh) -> float:
    return float(np.linalg.norm(face_cross(mesh), axis=1).sum() / 2.0)


def edges(mesh: Mesh) -> Edges:
    f = mesh.faces
    directed = np.concatenate([f[:, [0, 1]], f[:, [1, 2]], f[:, [2, 0]]])
    n = np.int64(len(mesh.vertices))
    d_keys = directed[:, 0] * n + directed[:, 1]
    _, d_counts = np.unique(d_keys, return_counts=True)
    lo, hi = directed.min(axis=1), directed.max(axis=1)
    _, u_counts = np.unique(lo * n + hi, return_counts=True)
    return Edges(
        boundary=int((u_counts == 1).sum()),
        non_manifold=int((u_counts > 2).sum()),
        same_direction=int((d_counts > 1).sum()),
    )


def signed_volume_mm3(mesh: Mesh) -> float:
    """Sum of signed tetrahedra from the origin; positive when faces point outwards."""
    a, b, c = corners(mesh)
    return float(np.einsum("ij,ij->i", a, np.cross(b, c)).sum() / 6.0)


def shells(mesh: Mesh) -> Ints:
    """Shell number per face: faces sharing a vertex are in the same shell (union-find)."""
    parent = list(range(len(mesh.vertices)))

    def root(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for a, b, c in mesh.faces.tolist():
        ra, rb, rc = root(a), root(b), root(c)
        parent[rb] = ra
        parent[rc] = ra
    roots = np.array([root(int(f[0])) for f in mesh.faces], dtype=np.int64)
    _, labels = np.unique(roots, return_inverse=True)
    result: Ints = labels.astype(np.int64)
    return result


def shell_volumes_mm3(mesh: Mesh, labels: Ints) -> list[float]:
    a, b, c = corners(mesh)
    per_face = np.einsum("ij,ij->i", a, np.cross(b, c)) / 6.0
    return [float(abs(per_face[labels == s].sum())) for s in range(int(labels.max()) + 1)]


def overhang_share(mesh: Mesh, max_from_vertical_deg: float, outward: float) -> float:
    """Share of the surface facing down more steeply than allowed, not counting the bed.
    `outward` is +1 or -1: -1 flips the normals of an inside-out mesh."""
    cross = face_cross(mesh) * outward
    double_area = np.linalg.norm(cross, axis=1)
    total = double_area.sum()
    if total == 0:
        return 0.0
    nz = np.divide(cross[:, 2], double_area, out=np.zeros(len(cross)), where=double_area > 0)
    a, b, c = corners(mesh)
    bottom = mesh.vertices[mesh.faces.reshape(-1), 2].min()
    on_bed = (np.stack([a[:, 2], b[:, 2], c[:, 2]]) <= bottom + BED_MM).all(axis=0)
    steep = (nz < -math.sin(math.radians(max_from_vertical_deg))) & ~on_bed
    return float(double_area[steep].sum() / total)


@dataclass(frozen=True)
class Walls:
    thinnest_mm: float | None  # the thinnest sampled wall, if any is under the largest limit
    thin_area_mm2: dict[float, float]  # surface thinner than each limit, scaled to the whole part
    sampled: int  # faces whose ray was cast


def walls(
    mesh: Mesh, limits_mm: list[float], max_rays: int, max_tests: int, outward: float
) -> Walls:
    """From the centre of each sampled face, cast a ray straight inwards and take the distance to
    the first surface it meets: the local wall thickness there. Only distances under the largest
    limit are measured; a thicker wall is just "thick enough"."""
    cross = face_cross(mesh) * outward
    double_area = np.linalg.norm(cross, axis=1)
    m = len(mesh.faces)
    rays = max(1, min(max_rays, m, max(200, max_tests // max(m, 1))))
    if rays >= m:
        sample = np.arange(m)
    else:
        sample = np.sort(np.random.default_rng(0).choice(m, size=rays, replace=False))
    usable = sample[double_area[sample] > 0]
    a, b, c = corners(mesh)
    unit = cross[usable] / double_area[usable, None]
    origins = (a[usable] + b[usable] + c[usable]) / 3.0
    thickness = _first_hits(origins, -unit, a, b - a, c - a, usable, max(limits_mm))
    area = double_area / 2.0
    scale = area.sum() / area[usable].sum() if len(usable) else 0.0
    thin = {limit: float(area[usable][thickness < limit].sum() * scale) for limit in limits_mm}
    finite = thickness[np.isfinite(thickness)]
    return Walls(
        thinnest_mm=float(finite.min()) if len(finite) else None,
        thin_area_mm2=thin,
        sampled=len(usable),
    )


def _first_hits(
    origins: Floats,
    directions: Floats,
    v0: Floats,
    e1: Floats,
    e2: Floats,
    own: Ints,
    reach: float,
) -> Floats:
    """Distance along each ray to the first triangle it meets, or infinity beyond `reach`.
    Only walls thinner than the largest limit matter, so a triangle whose bounding box is further
    than `reach` from the ray's start is skipped before the exact (Moller-Trumbore) test."""
    out = np.full(len(origins), np.inf)
    lo = np.minimum(np.minimum(v0, v0 + e1), v0 + e2)
    hi = np.maximum(np.maximum(v0, v0 + e1), v0 + e2)
    batch = max(1, 4_000_000 // max(len(v0), 1))
    for start in range(0, len(origins), batch):
        o = origins[start : start + batch]
        gap = np.maximum(0.0, np.maximum(lo[None] - o[:, None], o[:, None] - hi[None]))
        near = np.einsum("ijk,ijk->ij", gap, gap) <= reach * reach
        near[np.arange(len(o)), own[start : start + batch]] = False  # a face does not hit itself
        ray, tri = np.nonzero(near)
        if len(ray) == 0:
            continue
        d, oo = directions[start + ray], o[ray]
        a, b1, b2 = v0[tri], e1[tri], e2[tri]
        p = np.cross(d, b2)
        det = np.einsum("ij,ij->i", p, b1)
        ok = np.abs(det) > 1e-12
        inv = np.divide(1.0, det, out=np.zeros_like(det), where=ok)
        t_vec = oo - a
        u = np.einsum("ij,ij->i", t_vec, p) * inv
        q = np.cross(t_vec, b1)
        v = np.einsum("ij,ij->i", d, q) * inv
        t = np.einsum("ij,ij->i", b2, q) * inv
        tol = 1e-9
        hit = ok & (u >= -tol) & (v >= -tol) & (u + v <= 1 + tol) & (t > 1e-6)
        best = np.full(len(o), np.inf)
        np.minimum.at(best, ray[hit], t[hit])
        out[start : start + batch] = best
    return out
