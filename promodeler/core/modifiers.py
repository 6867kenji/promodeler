"""Non-destructive finishing operations applied to a part in order.

They map to Blender modifiers in the kernel, but the contract here is what
matters: widths are model-local meters, levels are bounded, and invalid
values raise instead of being clamped.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, fields
from typing import ClassVar

from .diagnostics import ModelingError, finite_vector, is_finite
from .transform import Transform

AXES = ("x", "y", "z")
BOOLEAN_OPERATIONS = ("difference", "union", "intersect")
BOOLEAN_SOLVERS = ("exact", "fast", "manifold")


@dataclass(frozen=True)
class Modifier:
    kind: ClassVar[str] = ""

    def validate(self, label: str) -> None:
        for f in fields(self):
            value = getattr(self, f.name)
            if isinstance(value, (int, float)) and not is_finite(value):
                raise ModelingError("modifier.nonFinite", f"{label}.{f.name} must be finite.")

    def to_recipe(self) -> dict:
        out: dict = {"kind": self.kind}
        for f in fields(self):
            value = getattr(self, f.name)
            if isinstance(value, tuple):
                value = list(value)
            out[f.name] = value
        return out


@dataclass(frozen=True)
class Bevel(Modifier):
    """Round or chamfer edges sharper than ``angle_limit``."""

    kind: ClassVar[str] = "bevel"
    width: float = 0.02
    segments: int = 1
    angle_limit: float = math.radians(30)

    def validate(self, label: str) -> None:
        super().validate(label)
        if self.width <= 0.0:
            raise ModelingError("bevel.width", f"{label}.width must be positive.")
        if not isinstance(self.segments, int) or not 1 <= self.segments <= 32:
            raise ModelingError("bevel.segments", f"{label}.segments must be in 1...32.")
        if not 0.0 < self.angle_limit <= math.pi:
            raise ModelingError("bevel.angleLimit", f"{label}.angle_limit must be in (0, pi].")


@dataclass(frozen=True)
class Subdivision(Modifier):
    """Catmull-Clark subdivision. ``levels`` applies to render and export."""

    kind: ClassVar[str] = "subdivision"
    levels: int = 1

    def validate(self, label: str) -> None:
        super().validate(label)
        if not isinstance(self.levels, int) or not 1 <= self.levels <= 6:
            raise ModelingError("subdivision.levels", f"{label}.levels must be in 1...6.")


@dataclass(frozen=True)
class Solidify(Modifier):
    """Give an open surface metric thickness. ``offset`` is -1 (inside) ... 1 (outside)."""

    kind: ClassVar[str] = "solidify"
    thickness: float = 0.01
    offset: float = -1.0

    def validate(self, label: str) -> None:
        super().validate(label)
        if self.thickness <= 0.0:
            raise ModelingError("solidify.thickness", f"{label}.thickness must be positive.")
        if not -1.0 <= self.offset <= 1.0:
            raise ModelingError("solidify.offset", f"{label}.offset must be in -1...1.")


@dataclass(frozen=True)
class Mirror(Modifier):
    """Mirror across the part's local planes; vertices within ``merge_distance`` of a plane weld.

    Geometry must not have faces lying on the mirror plane: they would be
    duplicated and make the result non-manifold. For a closed solid, author
    the full outline (see ``curves.symmetric``) instead of mirroring a half.
    """

    kind: ClassVar[str] = "mirror"
    axes: tuple[str, ...] = ("x",)
    merge_distance: float = 1e-4

    def validate(self, label: str) -> None:
        super().validate(label)
        if not self.axes or any(a not in AXES for a in self.axes) or len(set(self.axes)) != len(self.axes):
            raise ModelingError("mirror.axes", f"{label}.axes must be distinct entries from {AXES}.")
        if self.merge_distance < 0.0:
            raise ModelingError("mirror.merge", f"{label}.merge_distance must be nonnegative.")


@dataclass(frozen=True)
class Array(Modifier):
    """Repeat the geometry ``count`` times with a constant local offset in meters."""

    kind: ClassVar[str] = "array"
    count: int = 2
    offset: tuple[float, float, float] = (1.0, 0.0, 0.0)
    merge: bool = False

    def validate(self, label: str) -> None:
        super().validate(label)
        if not isinstance(self.count, int) or not 1 <= self.count <= 1000:
            raise ModelingError("array.count", f"{label}.count must be in 1...1000.")
        offset = finite_vector(self.offset, 3, "array.offset", f"{label}.offset")
        if max(abs(v) for v in offset) == 0.0:
            raise ModelingError("array.offset", f"{label}.offset must not be zero.")


@dataclass(frozen=True)
class Cutter:
    """Operand geometry for a boolean, positioned in the part's local space. Never exported."""

    shape: "Shape"  # noqa: F821 - imported lazily to avoid a cycle.
    transform: Transform = Transform()
    modifiers: tuple[Modifier, ...] = ()

    def validate(self, label: str) -> None:
        self.shape.validate(f"{label}.shape")
        self.transform.validate(f"{label}.transform")
        for index, modifier in enumerate(self.modifiers):
            if isinstance(modifier, Boolean):
                raise ModelingError("boolean.nested", f"{label}.modifiers[{index}] must not be a nested boolean.")
            modifier.validate(f"{label}.modifiers[{index}]")

    def to_recipe(self) -> dict:
        return {
            "shape": self.shape.to_recipe(),
            "transform": self.transform.to_recipe(),
            "modifiers": [m.to_recipe() for m in self.modifiers],
        }


@dataclass(frozen=True)
class Boolean(Modifier):
    """Exact CSG against an inline cutter. Both operands should be closed manifolds.

    ``exact`` is robust and default. ``manifold`` is faster and requires
    strictly manifold inputs; ``fast`` is approximate and only for previews.
    """

    kind: ClassVar[str] = "boolean"
    operation: str = "difference"
    cutter: Cutter | None = None
    solver: str = "exact"

    def validate(self, label: str) -> None:
        if self.operation not in BOOLEAN_OPERATIONS:
            raise ModelingError("boolean.operation", f"{label}.operation must be one of {BOOLEAN_OPERATIONS}.")
        if self.solver not in BOOLEAN_SOLVERS:
            raise ModelingError("boolean.solver", f"{label}.solver must be one of {BOOLEAN_SOLVERS}.")
        if self.cutter is None:
            raise ModelingError("boolean.cutter", f"{label}.cutter is required.")
        self.cutter.validate(f"{label}.cutter")

    def to_recipe(self) -> dict:
        return {"kind": self.kind, "operation": self.operation, "solver": self.solver, "cutter": self.cutter.to_recipe()}


MODIFIER_KINDS = {cls.kind: cls for cls in (Bevel, Subdivision, Solidify, Mirror, Array, Boolean)}
