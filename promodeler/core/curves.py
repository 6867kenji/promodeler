"""Point-list helpers for profiles and paths. All return plain tuples."""

from __future__ import annotations

import math

from .diagnostics import ModelingError


def circle(radius: float, segments: int = 32, center=(0.0, 0.0)):
    if segments < 3:
        raise ModelingError("curve.segments", "circle needs at least 3 segments.")
    cx, cy = center
    return tuple(
        (cx + radius * math.cos(2 * math.pi * i / segments), cy + radius * math.sin(2 * math.pi * i / segments))
        for i in range(segments)
    )


def regular_polygon(sides: int, radius: float, center=(0.0, 0.0), rotation: float = 0.0):
    if sides < 3:
        raise ModelingError("curve.sides", "regular_polygon needs at least 3 sides.")
    cx, cy = center
    return tuple(
        (cx + radius * math.cos(rotation + 2 * math.pi * i / sides), cy + radius * math.sin(rotation + 2 * math.pi * i / sides))
        for i in range(sides)
    )


def rect(width: float, height: float, center=(0.0, 0.0)):
    cx, cy = center
    hw, hh = width / 2, height / 2
    return ((cx - hw, cy - hh), (cx + hw, cy - hh), (cx + hw, cy + hh), (cx - hw, cy + hh))


def rounded_rect(width: float, height: float, radius: float, corner_segments: int = 4, center=(0.0, 0.0)):
    """Counterclockwise rounded rectangle. ``radius`` must fit within half the smaller side."""
    if radius <= 0 or radius > min(width, height) / 2:
        raise ModelingError("curve.radius", "rounded_rect radius must be positive and fit within the sides.")
    if corner_segments < 1:
        raise ModelingError("curve.segments", "rounded_rect needs at least 1 corner segment.")
    cx, cy = center
    hw, hh = width / 2 - radius, height / 2 - radius
    corners = ((hw, -hh, -math.pi / 2), (hw, hh, 0.0), (-hw, hh, math.pi / 2), (-hw, -hh, math.pi))
    points = []
    for ox, oy, start in corners:
        for i in range(corner_segments + 1):
            a = start + (math.pi / 2) * i / corner_segments
            points.append((cx + ox + radius * math.cos(a), cy + oy + radius * math.sin(a)))
    return tuple(points)


def arc(center, radius: float, start: float, end: float, segments: int = 8):
    """Points along a circular arc from ``start`` to ``end`` radians, endpoints included."""
    if segments < 1:
        raise ModelingError("curve.segments", "arc needs at least 1 segment.")
    cx, cy = center
    return tuple(
        (cx + radius * math.cos(start + (end - start) * i / segments), cy + radius * math.sin(start + (end - start) * i / segments))
        for i in range(segments + 1)
    )


def bezier(p0, p1, p2, p3, segments: int = 16):
    """Cubic Bezier samples (endpoints included) in 2D or 3D, matching the dimension of the inputs."""
    if segments < 1:
        raise ModelingError("curve.segments", "bezier needs at least 1 segment.")
    dims = len(p0)
    out = []
    for i in range(segments + 1):
        t = i / segments
        u = 1 - t
        out.append(tuple(
            u * u * u * p0[k] + 3 * u * u * t * p1[k] + 3 * u * t * t * p2[k] + t * t * t * p3[k] for k in range(dims)
        ))
    return tuple(out)


def polyline(*points):
    return tuple(tuple(float(c) for c in p) for p in points)


def symmetric(half, axis: str = "u"):
    """Complete a half outline by reflecting it across ``u = 0`` (or ``v = 0`` for ``axis="v"``).

    The half runs from one point on the axis to another; reflected copies of
    those two endpoints are dropped so the ring stays simple.
    """
    if axis not in ("u", "v"):
        raise ModelingError("curve.axis", "symmetric axis must be 'u' or 'v'.")
    k = 0 if axis == "u" else 1
    half = tuple(tuple(float(c) for c in p) for p in half)
    if len(half) < 2 or abs(half[0][k]) > 1e-12 or abs(half[-1][k]) > 1e-12:
        raise ModelingError("curve.symmetric", "symmetric needs a half outline starting and ending on the axis.")
    reflected = []
    for p in reversed(half[1:-1]):
        q = list(p)
        q[k] = -q[k]
        reflected.append(tuple(q))
    return half + tuple(reflected)


def join(*segments):
    """Concatenate point sequences, dropping duplicated joints."""
    out: list = []
    for seg in segments:
        for p in seg:
            if out and all(abs(a - b) < 1e-12 for a, b in zip(out[-1], p)):
                continue
            out.append(tuple(p))
    return tuple(out)
