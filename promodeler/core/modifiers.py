"""Non-destructive finishing operations applied to a part in order.

They map to Blender modifiers in the kernel, but the contract here is what
matters: widths are model-local meters, levels are bounded, and invalid
values raise instead of being clamped.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, fields
from typing import ClassVar

from .diagnostics import ModelingError, is_finite


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
            out[f.name] = getattr(self, f.name)
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


MODIFIER_KINDS = {cls.kind: cls for cls in (Bevel, Subdivision, Solidify)}
