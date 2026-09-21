"""Pure-Python surface generation for profile-based shapes.

Input is the recipe dictionary of a shape; output is a ``MeshSpec`` in
authoring space (Y up). Polygons are listed counterclockwise seen from
outside. Regions with holes are returned as ``Fill`` entries for the kernel
to triangulate, with the intended normal so orientation is never guessed.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from .diagnostics import ModelingError
from .mathutil import Vec3, add, cross, dot, normalize, scale, signed_area, sub, transform_direction, transform_point, trs


@dataclass
class Fill:
    loops: list[list[int]]
    normal: Vec3


@dataclass
class MeshSpec:
    vertices: list[Vec3] = field(default_factory=list)
    faces: list[list[int]] = field(default_factory=list)
    fills: list[Fill] = field(default_factory=list)

    def add_vertex(self, p: Vec3) -> int:
        self.vertices.append((float(p[0]), float(p[1]), float(p[2])))
        return len(self.vertices) - 1

    def add_cap(self, loops: list[list[int]], normal: Vec3) -> None:
        if len(loops) == 1:
            self.faces.append(list(loops[0]))
        else:
            self.fills.append(Fill([list(l) for l in loops], normal))


AXIS_VECTORS = {"x": (1.0, 0.0, 0.0), "y": (0.0, 1.0, 0.0), "z": (0.0, 0.0, 1.0)}


def _to_plane(u: float, v: float, axis: str) -> Vec3:
    if axis == "y":
        return (u, 0.0, -v)
    if axis == "z":
        return (u, v, 0.0)
    return (0.0, v, -u)


def _ccw(ring):
    return list(ring) if signed_area(ring) > 0 else list(reversed(ring))


def _ccw_keep_start(ring):
    ring = list(ring)
    return ring if signed_area(ring) > 0 else [ring[0]] + list(reversed(ring[1:]))


def _cw(ring):
    return list(ring) if signed_area(ring) < 0 else list(reversed(ring))


def _skin(spec: MeshSpec, ring_a: list[int], ring_b: list[int], wrap: bool) -> None:
    """Quads between two corresponding rings; ``ring_a`` is the earlier ring along the sweep direction."""
    n = len(ring_a)
    count = n if wrap else n - 1
    for j in range(count):
        j1 = (j + 1) % n
        spec.faces.append([ring_a[j], ring_a[j1], ring_b[j1], ring_b[j]])


def generate(shape: dict, quality: dict) -> MeshSpec:
    kind = shape["kind"]
    if kind == "extrude":
        return extrude(shape)
    if kind == "revolve":
        return revolve(shape, quality)
    if kind == "sweep":
        return sweep(shape)
    if kind == "loft":
        return loft(shape)
    raise ModelingError("shape.kind", f"meshgen does not handle shape kind {kind!r}.")


def extrude(shape: dict) -> MeshSpec:
    spec = MeshSpec()
    axis = shape["axis"]
    direction = scale(AXIS_VECTORS[axis], shape["depth"])
    rings = [_ccw(shape["profile"]["outer"])] + [_cw(h) for h in shape["profile"]["holes"]]
    bottoms, tops = [], []
    for ring in rings:
        bottom = [spec.add_vertex(_to_plane(u, v, axis)) for u, v in ring]
        top = [spec.add_vertex(add(_to_plane(u, v, axis), direction)) for u, v in ring]
        _skin(spec, bottom, top, wrap=True)
        bottoms.append(bottom)
        tops.append(top)
    normal = AXIS_VECTORS[axis]
    spec.add_cap([list(reversed(bottoms[0]))] + [list(reversed(b)) for b in bottoms[1:]], scale(normal, -1.0))
    spec.add_cap(tops, normal)
    return spec


def revolve(shape: dict, quality: dict) -> MeshSpec:
    spec = MeshSpec()
    points = [(float(r), float(h)) for r, h in shape["profile"]]
    segments = shape["segments"] or quality["curve_segments"]
    angle = shape["angle"]
    full = abs(angle - 2 * math.pi) < 1e-9
    closed = len(points) > 3 and points[0] == points[-1]
    if closed:
        points = points[:-1]
    polygon = list(points)
    if not closed:
        if points[-1][0] > 0:
            polygon.append((0.0, points[-1][1]))
        if points[0][0] > 0:
            polygon.append((0.0, points[0][1]))
    if signed_area(polygon) < 0:
        points.reverse()
    ring_count = segments if full else segments + 1
    rings: list[list[int]] = []
    for r, h in points:
        if r == 0.0:
            rings.append([spec.add_vertex((0.0, h, 0.0))])
            continue
        ring = []
        for j in range(ring_count):
            theta = angle * j / segments
            ring.append(spec.add_vertex((r * math.cos(theta), h, -r * math.sin(theta))))
        rings.append(ring)
    pairs = list(zip(rings, rings[1:]))
    if closed:
        pairs.append((rings[-1], rings[0]))
    for ring_a, ring_b in pairs:
        for j in range(segments):
            j1 = (j + 1) % ring_count
            a0 = ring_a[j % len(ring_a)]
            a1 = ring_a[j1 % len(ring_a)]
            b1 = ring_b[j1 % len(ring_b)]
            b0 = ring_b[j % len(ring_b)]
            face = []
            for v in (a0, a1, b1, b0):
                if v not in face:
                    face.append(v)
            if len(face) >= 3:
                spec.faces.append(face)
    if not closed and full and shape["cap_ends"]:
        if len(rings[0]) > 1:
            spec.faces.append(list(reversed(rings[0])))
        if len(rings[-1]) > 1:
            spec.faces.append(list(rings[-1]))
    return spec


def _frames(path: list[Vec3]) -> list[tuple[Vec3, Vec3, Vec3]]:
    """Rotation-minimizing (tangent, normal, binormal) frames via the double-reflection method."""
    n = len(path)
    tangents = []
    for i in range(n):
        if i == 0:
            t = sub(path[1], path[0])
        elif i == n - 1:
            t = sub(path[-1], path[-2])
        else:
            t = add(normalize(sub(path[i], path[i - 1])), normalize(sub(path[i + 1], path[i])))
            if dot(t, t) < 1e-12:
                t = sub(path[i + 1], path[i])
        tangents.append(normalize(t))
    up = (0.0, 1.0, 0.0)
    r0 = sub(up, scale(tangents[0], dot(up, tangents[0])))
    if dot(r0, r0) < 1e-8:
        alt = (1.0, 0.0, 0.0)
        r0 = sub(alt, scale(tangents[0], dot(alt, tangents[0])))
    r = normalize(r0)
    frames = [(tangents[0], r, cross(tangents[0], r))]
    for i in range(n - 1):
        v1 = sub(path[i + 1], path[i])
        c1 = dot(v1, v1)
        r_l = sub(r, scale(v1, 2.0 / c1 * dot(v1, r)))
        t_l = sub(tangents[i], scale(v1, 2.0 / c1 * dot(v1, tangents[i])))
        v2 = sub(tangents[i + 1], t_l)
        c2 = dot(v2, v2)
        r = r_l if c2 < 1e-14 else sub(r_l, scale(v2, 2.0 / c2 * dot(v2, r_l)))
        r = normalize(sub(r, scale(tangents[i + 1], dot(r, tangents[i + 1]))))
        frames.append((tangents[i + 1], r, cross(tangents[i + 1], r)))
    return frames


def sweep(shape: dict) -> MeshSpec:
    spec = MeshSpec()
    profile = _ccw(shape["profile"]["outer"])
    path = [tuple(float(c) for c in p) for p in shape["path"]]
    scales = shape["scales"] or [1.0] * len(path)
    twist = shape["twist"]
    frames = _frames(path)
    lengths = [0.0]
    for i in range(1, len(path)):
        lengths.append(lengths[-1] + math.dist(path[i - 1], path[i]))
    total = lengths[-1] or 1.0
    rings: list[list[int]] = []
    for i, (p, (t, r, s)) in enumerate(zip(path, frames)):
        phi = twist * lengths[i] / total
        c, sn = math.cos(phi), math.sin(phi)
        ring = []
        for u, v in profile:
            ur = (u * c - v * sn) * scales[i]
            vr = (u * sn + v * c) * scales[i]
            ring.append(spec.add_vertex(add(p, add(scale(r, ur), scale(s, vr)))))
        rings.append(ring)
    for ring_a, ring_b in zip(rings, rings[1:]):
        _skin(spec, ring_a, ring_b, wrap=True)
    if shape["capped"]:
        spec.faces.append(list(reversed(rings[0])))
        spec.faces.append(list(rings[-1]))
    return spec


def loft(shape: dict) -> MeshSpec:
    spec = MeshSpec()
    rings: list[list[int]] = []
    normals: list[Vec3] = []
    for section in shape["sections"]:
        points = _ccw_keep_start(section["points"])
        tf = section["transform"]
        m = trs(tuple(tf["translation"]), tuple(tf["rotation"]), tuple(tf["scale"]))
        rings.append([spec.add_vertex(transform_point(m, _to_plane(u, v, "y"))) for u, v in points])
        normals.append(normalize(transform_direction(m, (0.0, 1.0, 0.0))))
    for ring_a, ring_b in zip(rings, rings[1:]):
        _skin(spec, ring_a, ring_b, wrap=True)
    if shape["capped"]:
        spec.faces.append(list(reversed(rings[0])))
        spec.faces.append(list(rings[-1]))
    return spec
