"""Base shapes. Each dataclass has a ``kind`` tag the kernel dispatches on.

Segment counts default to the quality profile when ``None``. Every shape is
centered on its local origin; height axes run along local Y.
"""

from __future__ import annotations

from dataclasses import dataclass, fields
from typing import ClassVar

from .diagnostics import ModelingError, is_finite


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


SHAPE_KINDS = {cls.kind: cls for cls in (Box, Plane, Cylinder, Cone, Sphere)}
