from __future__ import annotations

import math

from mathutils import Euler, Matrix, Vector

# Authoring (Y up, +Z toward viewer) -> Blender (Z up, -Y toward viewer).
# A +90 degree rotation about X maps (x, y, z) to (x, -z, y).
A2B = Matrix.Rotation(math.radians(90.0), 4, "X")
B2A = A2B.inverted()


def author_trs_to_matrix(transform: dict) -> Matrix:
    t = Vector(transform["translation"])
    r = Euler(transform["rotation"], "XYZ").to_matrix().to_4x4()
    s = Matrix.Diagonal((*transform["scale"], 1.0))
    return Matrix.Translation(t) @ r @ s


def author_to_blender_matrix(transform: dict) -> Matrix:
    """Conjugate an authored local matrix into Blender's frame."""
    return A2B @ author_trs_to_matrix(transform) @ B2A


def blender_point_to_author(point: Vector) -> tuple[float, float, float]:
    p = B2A @ point
    return (p.x, p.y, p.z)
