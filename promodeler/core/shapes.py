"""Base shapes. Each dataclass has a ``kind`` tag the kernel dispatches on.

Segment counts default to the quality profile when ``None``. Primitive
shapes are centered on their local origin with height along local Y.
Profile-based shapes document their own placement.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, fields
from typing import ClassVar

from .diagnostics import ModelingError, is_finite
from .profile import Profile, validate_ring
from .transform import Transform

AXES = ("x", "y", "z")


@dataclass(frozen=True)
class Shape:
    kind: ClassVar[str] = ""

    def validate(self, label: str) -> None:
        for f in fields(self):
            value = getattr(self, f.name)
            if isinstance(value, (int, float)) and not is_finite(value):
                raise ModelingError("shape.nonFinite", f"{label}.{f.name} must be finite.")

    def to_recipe(self) -> dict:
        out: dict = {"kind": self.kind}
        for f in fields(self):
            value = getattr(self, f.name)
            if isinstance(value, tuple):
                value = [float(v) for v in value]
            out[f.name] = value
        return out


def _positive(value: float, code: str, label: str) -> None:
    if not is_finite(value) or value <= 0.0:
        raise ModelingError(code, f"{label} must be positive and finite, got {value!r}.")


def _segments(value: int | None, minimum: int, code: str, label: str) -> None:
    if value is None:
        return
    if not isinstance(value, int) or value < minimum or value > 4096:
        raise ModelingError(code, f"{label} must be an integer in {minimum}...4096, got {value!r}.")


@dataclass(frozen=True)
class Box(Shape):
    kind: ClassVar[str] = "box"
    size: tuple[float, float, float] = (1.0, 1.0, 1.0)

    def validate(self, label: str) -> None:
        super().validate(label)
        if len(self.size) != 3:
            raise ModelingError("box.size", f"{label}.size needs 3 components.")
        for v in self.size:
            _positive(v, "box.size", f"{label}.size")


@dataclass(frozen=True)
class Plane(Shape):
    """A flat quad in the local XZ plane facing +Y."""

    kind: ClassVar[str] = "plane"
    size: tuple[float, float] = (1.0, 1.0)

    def validate(self, label: str) -> None:
        super().validate(label)
        if len(self.size) != 2:
            raise ModelingError("plane.size", f"{label}.size needs 2 components.")
        for v in self.size:
            _positive(v, "plane.size", f"{label}.size")


@dataclass(frozen=True)
class Cylinder(Shape):
    kind: ClassVar[str] = "cylinder"
    radius: float = 0.5
    height: float = 1.0
    segments: int | None = None

    def validate(self, label: str) -> None:
        super().validate(label)
        _positive(self.radius, "cylinder.radius", f"{label}.radius")
        _positive(self.height, "cylinder.height", f"{label}.height")
        _segments(self.segments, 3, "cylinder.segments", f"{label}.segments")


@dataclass(frozen=True)
class Cone(Shape):
    """Truncated when ``top_radius`` is positive; a point when zero."""

    kind: ClassVar[str] = "cone"
    radius: float = 0.5
    height: float = 1.0
    top_radius: float = 0.0
    segments: int | None = None

    def validate(self, label: str) -> None:
        super().validate(label)
        _positive(self.radius, "cone.radius", f"{label}.radius")
        _positive(self.height, "cone.height", f"{label}.height")
        if not is_finite(self.top_radius) or self.top_radius < 0.0:
            raise ModelingError("cone.topRadius", f"{label}.top_radius must be nonnegative.")
        _segments(self.segments, 3, "cone.segments", f"{label}.segments")


@dataclass(frozen=True)
class Sphere(Shape):
    kind: ClassVar[str] = "sphere"
    radius: float = 0.5
    segments: int | None = None
    rings: int | None = None

    def validate(self, label: str) -> None:
        super().validate(label)
        _positive(self.radius, "sphere.radius", f"{label}.radius")
        _segments(self.segments, 3, "sphere.segments", f"{label}.segments")
        _segments(self.rings, 2, "sphere.rings", f"{label}.rings")


@dataclass(frozen=True)
class Extrude(Shape):
    """A profile (with holes) extruded by ``depth`` along ``axis`` from the origin plane.

    For ``axis="y"`` the profile lies on the ground: (u, v) maps to (x, 0, -v)
    so a counterclockwise drawing seen from above faces +Y. ``"z"`` maps
    (u, v) to (u, v, 0) as if drawn on a sheet facing the viewer; ``"x"``
    maps to (0, v, -u). Caps with holes are triangulated.
    """

    kind: ClassVar[str] = "extrude"
    profile: Profile = Profile(((0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)))
    depth: float = 1.0
    axis: str = "y"

    def validate(self, label: str) -> None:
        super().validate(label)
        self.profile.validate(f"{label}.profile")
        _positive(self.depth, "extrude.depth", f"{label}.depth")
        if self.axis not in AXES:
            raise ModelingError("extrude.axis", f"{label}.axis must be one of {AXES}.")

    def to_recipe(self) -> dict:
        return {"kind": self.kind, "profile": self.profile.to_recipe(), "depth": float(self.depth), "axis": self.axis}


@dataclass(frozen=True)
class Revolve(Shape):
    """An ordered (radius, height) profile revolved about local Y.

    Interior points need positive radius; a zero radius is allowed only at
    the endpoints and closes the surface with a pole. Winding is normalized
    so faces point outward regardless of traversal direction. A profile
    whose first and last points coincide forms a closed loop (a torus). Open
    profiles with positive endpoint radii receive flat caps when
    ``cap_ends`` is set. Partial revolutions (``angle`` below 2 pi) stay
    open on their two side faces.
    """

    kind: ClassVar[str] = "revolve"
    profile: tuple[tuple[float, float], ...] = ((0.0, 0.0), (0.5, 0.0), (0.5, 1.0), (0.0, 1.0))
    segments: int | None = None
    angle: float = 2 * math.pi
    cap_ends: bool = True

    def validate(self, label: str) -> None:
        super().validate(label)
        try:
            points = tuple((float(p[0]), float(p[1])) for p in self.profile)
        except (TypeError, IndexError):
            raise ModelingError("revolve.profile", f"{label}.profile must be (radius, height) pairs.") from None
        if len(points) < 2:
            raise ModelingError("revolve.profile", f"{label}.profile needs at least 2 points.")
        if not all(is_finite(r) and is_finite(h) for r, h in points):
            raise ModelingError("revolve.profile", f"{label}.profile must be finite.")
        closed = len(points) > 3 and points[0] == points[-1]
        interior = points[1:-1] if not closed else points[:-1]
        for r, _ in points:
            if r < 0:
                raise ModelingError("revolve.profile", f"{label}.profile radii must be nonnegative.")
        for r, _ in interior:
            if r == 0:
                raise ModelingError("revolve.profile", f"{label}.profile allows zero radius only at the endpoints.")
        for i in range(len(points) - 1):
            if points[i] == points[i + 1]:
                raise ModelingError("revolve.profile", f"{label}.profile has consecutive duplicate points at {i}.")
        if points[0][0] == 0 and points[-1][0] == 0 and len(points) == 2:
            raise ModelingError("revolve.profile", f"{label}.profile lies entirely on the axis.")
        _segments(self.segments, 3, "revolve.segments", f"{label}.segments")
        if not is_finite(self.angle) or not 0 < self.angle <= 2 * math.pi + 1e-9:
            raise ModelingError("revolve.angle", f"{label}.angle must be in (0, 2*pi].")

    def to_recipe(self) -> dict:
        return {
            "kind": self.kind,
            "profile": [[float(r), float(h)] for r, h in self.profile],
            "segments": self.segments,
            "angle": float(self.angle),
            "cap_ends": bool(self.cap_ends),
        }


@dataclass(frozen=True)
class Sweep(Shape):
    """A hole-free profile swept along an open 3D polyline with rotation-minimizing frames.

    The profile's (u, v) axes follow the frame's normal and binormal, which
    start as close to +Y as the first tangent allows. ``scales`` gives one
    factor per path point; ``twist`` is the total rotation in radians
    distributed along the path length.
    """

    kind: ClassVar[str] = "sweep"
    profile: Profile = Profile(((0.1, 0.0), (0.0, 0.1), (-0.1, 0.0), (0.0, -0.1)))
    path: tuple[tuple[float, float, float], ...] = ((0.0, 0.0, 0.0), (0.0, 1.0, 0.0))
    scales: tuple[float, ...] | None = None
    twist: float = 0.0
    capped: bool = True

    def validate(self, label: str) -> None:
        super().validate(label)
        self.profile.validate(f"{label}.profile")
        if self.profile.holes:
            raise ModelingError("sweep.profile", f"{label}.profile must not have holes.")
        try:
            path = tuple((float(p[0]), float(p[1]), float(p[2])) for p in self.path)
        except (TypeError, IndexError):
            raise ModelingError("sweep.path", f"{label}.path must be (x, y, z) triples.") from None
        if len(path) < 2 or len(path) > 4096:
            raise ModelingError("sweep.path", f"{label}.path needs 2...4096 points.")
        if not all(all(is_finite(c) for c in p) for p in path):
            raise ModelingError("sweep.path", f"{label}.path must be finite.")
        for i in range(len(path) - 1):
            a, b = path[i], path[i + 1]
            if math.dist(a, b) < 1e-9:
                raise ModelingError("sweep.path", f"{label}.path has a zero-length span at {i}.")
        for i in range(1, len(path) - 1):
            d0 = tuple(path[i][k] - path[i - 1][k] for k in range(3))
            d1 = tuple(path[i + 1][k] - path[i][k] for k in range(3))
            cosine = sum(d0[k] * d1[k] for k in range(3)) / (math.dist(path[i - 1], path[i]) * math.dist(path[i], path[i + 1]))
            if cosine < -0.999:
                raise ModelingError("sweep.path", f"{label}.path reverses exactly at {i}.")
        if self.scales is not None:
            if len(self.scales) != len(path):
                raise ModelingError("sweep.scales", f"{label}.scales needs one value per path point.")
            for s in self.scales:
                _positive(s, "sweep.scales", f"{label}.scales")
        if not is_finite(self.twist):
            raise ModelingError("sweep.twist", f"{label}.twist must be finite.")

    def to_recipe(self) -> dict:
        return {
            "kind": self.kind,
            "profile": self.profile.to_recipe(),
            "path": [[float(c) for c in p] for p in self.path],
            "scales": None if self.scales is None else [float(s) for s in self.scales],
            "twist": float(self.twist),
            "capped": bool(self.capped),
        }


@dataclass(frozen=True)
class LoftSection:
    """A ring of (u, v) points on the local XZ plane facing +Y, placed by ``transform``."""

    points: tuple[tuple[float, float], ...]
    transform: Transform = Transform()

    def to_recipe(self) -> dict:
        return {"points": [[float(u), float(v)] for u, v in self.points], "transform": self.transform.to_recipe()}


@dataclass(frozen=True)
class Loft(Shape):
    """Skin consecutive sections with matching point counts. Point 0 of every section corresponds."""

    kind: ClassVar[str] = "loft"
    sections: tuple[LoftSection, ...] = ()
    capped: bool = True

    def validate(self, label: str) -> None:
        super().validate(label)
        if len(self.sections) < 2:
            raise ModelingError("loft.sections", f"{label}.sections needs at least 2 sections.")
        counts = set()
        for i, section in enumerate(self.sections):
            validate_ring(section.points, f"{label}.sections[{i}].points", "loft.section")
            section.transform.validate(f"{label}.sections[{i}].transform")
            counts.add(len(section.points))
        if len(counts) != 1:
            raise ModelingError("loft.sections", f"{label}.sections must all have the same point count.")

    def to_recipe(self) -> dict:
        return {"kind": self.kind, "sections": [s.to_recipe() for s in self.sections], "capped": bool(self.capped)}


SHAPE_KINDS = {cls.kind: cls for cls in (Box, Plane, Cylinder, Cone, Sphere, Extrude, Revolve, Sweep, Loft)}
