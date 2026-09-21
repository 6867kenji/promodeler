from __future__ import annotations

from dataclasses import dataclass

from .color import Color
from .diagnostics import ModelingError, is_finite

ALPHA_MODES = ("opaque", "blend")


@dataclass(frozen=True)
class Material:
    """A principled PBR surface. M0 exposes the scalar channels only.

    ``alpha_mode`` is explicit: a color alpha below one never selects
    blending by itself.
    """

    id: str
    base_color: Color = Color(0.8, 0.8, 0.8)
    roughness: float = 0.5
    metallic: float = 0.0
    emission_color: Color = Color(0.0, 0.0, 0.0)
    emission_strength: float = 0.0
    alpha_mode: str = "opaque"
    double_sided: bool = False

    def validate(self) -> None:
        label = f"material[{self.id!r}]"
        if not isinstance(self.id, str) or not self.id or any(c.isspace() for c in self.id):
            raise ModelingError("material.id", f"{label}.id must be a nonempty string without whitespace.")
        self.base_color.validate(f"{label}.base_color")
        self.emission_color.validate(f"{label}.emission_color")
        for name in ("roughness", "metallic"):
            value = getattr(self, name)
            if not is_finite(value) or not 0.0 <= value <= 1.0:
                raise ModelingError(f"material.{name}", f"{label}.{name} must be within 0...1.")
        if not is_finite(self.emission_strength) or self.emission_strength < 0.0:
            raise ModelingError("material.emissionStrength", f"{label}.emission_strength must be nonnegative.")
        if self.alpha_mode not in ALPHA_MODES:
            raise ModelingError("material.alphaMode", f"{label}.alpha_mode must be one of {ALPHA_MODES}.")
        if self.alpha_mode == "opaque" and self.base_color.a != 1.0:
            raise ModelingError(
                "material.alphaMode",
                f"{label} has base_color alpha {self.base_color.a} but alpha_mode 'opaque'; choose 'blend' explicitly.",
            )

    def to_recipe(self) -> dict:
        return {
            "id": self.id,
            "base_color": self.base_color.to_recipe(),
            "roughness": float(self.roughness),
            "metallic": float(self.metallic),
            "emission_color": self.emission_color.to_recipe(),
            "emission_strength": float(self.emission_strength),
            "alpha_mode": self.alpha_mode,
            "double_sided": bool(self.double_sided),
        }
