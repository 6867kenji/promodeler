"""Small pure-Python vector helpers so mesh generation stays testable without Blender."""

from __future__ import annotations

import math

Vec2 = tuple[float, float]
Vec3 = tuple[float, float, float]
Mat34 = tuple[tuple[float, float, float, float], ...]


def add(a: Vec3, b: Vec3) -> Vec3:
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def sub(a: Vec3, b: Vec3) -> Vec3:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def scale(a: Vec3, s: float) -> Vec3:
    return (a[0] * s, a[1] * s, a[2] * s)


def dot(a: Vec3, b: Vec3) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def cross(a: Vec3, b: Vec3) -> Vec3:
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def length(a: Vec3) -> float:
    return math.sqrt(dot(a, a))


def normalize(a: Vec3) -> Vec3:
    n = length(a)
    return (0.0, 0.0, 0.0) if n == 0.0 else (a[0] / n, a[1] / n, a[2] / n)


def euler_xyz(rx: float, ry: float, rz: float) -> tuple[Vec3, Vec3, Vec3]:
    """Rotation matrix rows for Blender's XYZ Euler order: Rz * Ry * Rx."""
    cx, sx = math.cos(rx), math.sin(rx)
    cy, sy = math.cos(ry), math.sin(ry)
    cz, sz = math.cos(rz), math.sin(rz)
    return (
        (cy * cz, sx * sy * cz - cx * sz, cx * sy * cz + sx * sz),
        (cy * sz, sx * sy * sz + cx * cz, cx * sy * sz - sx * cz),
        (-sy, sx * cy, cx * cy),
    )


def trs(translation: Vec3, rotation: Vec3, scaling: Vec3) -> Mat34:
    r = euler_xyz(*rotation)
    return tuple(
        (r[i][0] * scaling[0], r[i][1] * scaling[1], r[i][2] * scaling[2], translation[i]) for i in range(3)
    )


def transform_point(m: Mat34, p: Vec3) -> Vec3:
    return tuple(m[i][0] * p[0] + m[i][1] * p[1] + m[i][2] * p[2] + m[i][3] for i in range(3))  # type: ignore[return-value]


def transform_direction(m: Mat34, d: Vec3) -> Vec3:
    return tuple(m[i][0] * d[0] + m[i][1] * d[1] + m[i][2] * d[2] for i in range(3))  # type: ignore[return-value]


def signed_area(points) -> float:
    """Shoelace area of a closed 2D ring; positive when counterclockwise."""
    area = 0.0
    n = len(points)
    for i in range(n):
        x0, y0 = points[i]
        x1, y1 = points[(i + 1) % n]
        area += x0 * y1 - x1 * y0
    return area * 0.5


def polygon_volume(vertices, faces) -> float:
    """Signed volume of closed polygon soup via fan triangulation. Positive when normals face outward."""
    total = 0.0
    for face in faces:
        a = vertices[face[0]]
        for i in range(1, len(face) - 1):
            b = vertices[face[i]]
            c = vertices[face[i + 1]]
            total += dot(a, cross(b, c))
    return total / 6.0


def face_normal(vertices, face) -> Vec3:
    """Newell normal of a polygon, robust for concave planar faces."""
    nx = ny = nz = 0.0
    n = len(face)
    for i in range(n):
        x0, y0, z0 = vertices[face[i]]
        x1, y1, z1 = vertices[face[(i + 1) % n]]
        nx += (y0 - y1) * (z0 + z1)
        ny += (z0 - z1) * (x0 + x1)
        nz += (x0 - x1) * (y0 + y1)
    return normalize((nx, ny, nz))
