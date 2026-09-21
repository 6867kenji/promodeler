"""2D profiles: simple rings with optional disjoint holes."""

from __future__ import annotations

from dataclasses import dataclass

from .diagnostics import ModelingError, is_finite
from .mathutil import signed_area

Ring = tuple[tuple[float, float], ...]


def _orient(a, b, c) -> float:
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def segments_intersect(p1, p2, q1, q2) -> bool:
    """Proper crossing of two segments, endpoints excluded."""
    d1 = _orient(q1, q2, p1)
    d2 = _orient(q1, q2, p2)
    d3 = _orient(p1, p2, q1)
    d4 = _orient(p1, p2, q2)
    return ((d1 > 0) != (d2 > 0)) and ((d3 > 0) != (d4 > 0)) and d1 != 0 and d2 != 0 and d3 != 0 and d4 != 0


def point_in_ring(point, ring: Ring) -> bool:
    x, y = point
    inside = False
    n = len(ring)
    for i in range(n):
        x0, y0 = ring[i]
        x1, y1 = ring[(i + 1) % n]
        if (y0 > y) != (y1 > y):
            t = (y - y0) / (y1 - y0)
            if x < x0 + t * (x1 - x0):
                inside = not inside
    return inside


def ring_self_intersects(ring: Ring) -> bool:
    n = len(ring)
    for i in range(n):
        for j in range(i + 2, n):
            if i == 0 and j == n - 1:
                continue
            if segments_intersect(ring[i], ring[(i + 1) % n], ring[j], ring[(j + 1) % n]):
                return True
    return False


def rings_cross(a: Ring, b: Ring) -> bool:
    for i in range(len(a)):
        for j in range(len(b)):
            if segments_intersect(a[i], a[(i + 1) % len(a)], b[j], b[(j + 1) % len(b)]):
                return True
    return False


def validate_ring(ring, label: str, code: str) -> Ring:
    try:
        ring = tuple((float(p[0]), float(p[1])) for p in ring)
    except (TypeError, IndexError):
        raise ModelingError(code, f"{label} must be a sequence of (u, v) pairs.") from None
    if len(ring) < 3:
        raise ModelingError(code, f"{label} needs at least 3 points.")
    if not all(is_finite(u) and is_finite(v) for u, v in ring):
        raise ModelingError(code, f"{label} must be finite.")
    if len(ring) > 4096:
        raise ModelingError(code, f"{label} has more than 4096 points.")
    for i in range(len(ring)):
        if ring[i] == ring[(i + 1) % len(ring)]:
            raise ModelingError(code, f"{label} has consecutive duplicate points at index {i}.")
    if abs(signed_area(ring)) < 1e-12:
        raise ModelingError(code, f"{label} has zero area.")
    if ring_self_intersects(ring):
        raise ModelingError(code, f"{label} intersects itself.")
    return ring


@dataclass(frozen=True)
class Profile:
    """A simple outer ring and disjoint holes strictly inside it. Winding is normalized by the builders."""

    outer: Ring
    holes: tuple[Ring, ...] = ()

    def validate(self, label: str = "profile") -> None:
        outer = validate_ring(self.outer, f"{label}.outer", "profile.outer")
        holes = [validate_ring(h, f"{label}.holes[{i}]", "profile.hole") for i, h in enumerate(self.holes)]
        for i, hole in enumerate(holes):
            if not all(point_in_ring(p, outer) for p in hole) or rings_cross(hole, outer):
                raise ModelingError("profile.hole", f"{label}.holes[{i}] must lie strictly inside the outer ring.")
            for j in range(i):
                other = holes[j]
                if rings_cross(hole, other) or any(point_in_ring(p, other) for p in hole) or any(
                    point_in_ring(p, hole) for p in other
                ):
                    raise ModelingError("profile.hole", f"{label}.holes[{i}] overlaps holes[{j}].")

    def to_recipe(self) -> dict:
        return {
            "outer": [[float(u), float(v)] for u, v in self.outer],
            "holes": [[[float(u), float(v)] for u, v in hole] for hole in self.holes],
        }
