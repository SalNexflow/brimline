"""A small preview picture of a mesh: three views (top, front, side), shaded, as a PNG.

Drawn with numpy and written with zlib, so no imaging library is needed. Used on the file page
and as the picture an optional vision model may comment on (advice only)."""

import struct
import zlib

import numpy as np

from brimline_engine.files.mesh import Floats, Mesh

VIEW_PX = 220
GAP_PX = 10
MAX_TRIANGLES = 20_000  # the largest triangles are drawn first; the rest are too small to see


def render_png(mesh: Mesh) -> bytes:
    tris = mesh.vertices[mesh.faces]
    if len(tris) > MAX_TRIANGLES:
        area = np.linalg.norm(np.cross(tris[:, 1] - tris[:, 0], tris[:, 2] - tris[:, 0]), axis=1)
        tris = tris[np.argsort(area)[-MAX_TRIANGLES:]]
    lo, hi = tris.reshape(-1, 3).min(axis=0), tris.reshape(-1, 3).max(axis=0)
    scale = (VIEW_PX - 20) / max(float((hi - lo).max()), 1e-9)
    # (screen x axis, screen y axis, depth axis towards the viewer)
    views = [(0, 1, 2), (0, 2, 1), (1, 2, 0)]  # top, front (looking along +y), side
    image = np.full((VIEW_PX, 3 * VIEW_PX + 2 * GAP_PX), 255, dtype=np.uint8)
    for i, (ax, ay, az) in enumerate(views):
        flip_depth = az == 1  # the front view looks along +y, so smaller y is nearer
        view = _draw(tris, lo, scale, ax, ay, az, flip_depth)
        x0 = i * (VIEW_PX + GAP_PX)
        image[:, x0 : x0 + VIEW_PX] = view
    return _png(image)


def _draw(
    tris: Floats, lo: Floats, scale: float, ax: int, ay: int, az: int, flip_depth: bool
) -> np.ndarray:
    size = VIEW_PX
    out = np.full((size, size), 255, dtype=np.uint8)
    depth = np.full((size, size), -np.inf)
    normal = np.cross(tris[:, 1] - tris[:, 0], tris[:, 2] - tris[:, 0])
    length = np.linalg.norm(normal, axis=1)
    toward = normal[:, az] * (-1 if flip_depth else 1)
    shade = np.where(length > 0, np.abs(toward) / np.maximum(length, 1e-12), 0)
    for t, s in zip(tris, shade, strict=True):
        px = (t[:, ax] - lo[ax]) * scale + 10
        py = size - 1 - ((t[:, ay] - lo[ay]) * scale + 10)  # y up on screen
        pz = t[:, az] * (-1 if flip_depth else 1)
        x_min, x_max = max(int(px.min()), 0), min(int(np.ceil(px.max())), size - 1)
        y_min, y_max = max(int(py.min()), 0), min(int(np.ceil(py.max())), size - 1)
        if x_min > x_max or y_min > y_max:
            continue
        xs, ys = np.meshgrid(np.arange(x_min, x_max + 1) + 0.5, np.arange(y_min, y_max + 1) + 0.5)
        d = (py[1] - py[2]) * (px[0] - px[2]) + (px[2] - px[1]) * (py[0] - py[2])
        if abs(d) < 1e-12:
            continue
        w0 = ((py[1] - py[2]) * (xs - px[2]) + (px[2] - px[1]) * (ys - py[2])) / d
        w1 = ((py[2] - py[0]) * (xs - px[2]) + (px[0] - px[2]) * (ys - py[2])) / d
        w2 = 1 - w0 - w1
        inside = (w0 >= 0) & (w1 >= 0) & (w2 >= 0)
        z = w0 * pz[0] + w1 * pz[1] + w2 * pz[2]
        region = depth[y_min : y_max + 1, x_min : x_max + 1]
        nearer = inside & (z > region)
        region[nearer] = z[nearer]
        out[y_min : y_max + 1, x_min : x_max + 1][nearer] = int(70 + 150 * s)
    return out


def _png(gray: np.ndarray) -> bytes:
    height, width = gray.shape
    raw = b"".join(b"\x00" + gray[y].tobytes() for y in range(height))

    def chunk(kind: bytes, data: bytes) -> bytes:
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))

    header = struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0)  # 8-bit grayscale
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(raw, 9))
        + chunk(b"IEND", b"")
    )
