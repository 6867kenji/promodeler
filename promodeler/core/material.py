"""Layered PBR materials.

Every channel accepts a constant or a field. A material whose channels are
all constants compiles straight to renderer parameters. Any field, or any
layer, makes the material procedural: the kernel bakes it to a PBR texture
set (base color, roughness, metallic, normal, emission) in the part's UVs
and both the verification render and the export use those textures.
"""

from __future__ import annotations

from dataclasses import dataclass, fields as dc_fields

from .color import Color
from .diagnostics import ModelingError, is_finite
from .fields import ColorField, Field, color_recipe, is_constant, scalar_recipe, validate_field

ALPHA_MODES = ("opaque", "blend")
SCALAR_CHANNELS = ("roughness", "metallic", "emission_strength", "height")
COLOR_CHANNELS = ("base_color", "emission_color")


@dataclass(frozen=True)
class Layer:
    """A partial override blended over what lies below it by ``mask`` (0 keeps, 1 replaces).

    Unspecified channels pass through. ``height`` is in meters and feeds
    the bump normal together with the base height.
    """

    base_color: Color | ColorField | None = None
    roughness: float | Field | None = None
    metallic: float | Field | None = None
    height: float | Field | None = None
    emission_color: Color | ColorField | None = None
    emission_strength: float | Field | None = None
    mask: float | Field = 1.0

    def validate(self, label: str) -> None:
        specified = False
        for f in dc_fields(self):
            value = getattr(self, f.name)
            if value is None:
                continue
            validate_field(value, f"{label}.{f.name}")
            if f.name in COLOR_CHANNELS and not isinstance(value, (Color, ColorField)):
                raise ModelingError("layer.channel", f"{label}.{f.name} must be a Color or color field.")
            if f.name in SCALAR_CHANNELS + ("mask",) and isinstance(value, (Color, ColorField)):
                raise ModelingError("layer.channel", f"{label}.{f.name} must be a number or scalar field.")
            if f.name != "mask":
                specified = True
        if not specified:
            raise ModelingError("layer.empty", f"{label} specifies no channel.")

    def to_recipe(self) -> dict:
        out: dict = {}
        for name in COLOR_CHANNELS:
            value = getattr(self, name)
            out[name] = None if value is None else color_recipe(value)
        for name in SCALAR_CHANNELS:
            value = getattr(self, name)
            out[name] = None if value is None else scalar_recipe(value)
        out["mask"] = scalar_recipe(self.mask)
        return out

    def has_fields(self) -> bool:
        return any(getattr(self, f.name) is not None and not is_constant(getattr(self, f.name)) for f in dc_fields(self))


@dataclass(frozen=True)
class Material:
    """A principled PBR surface with optional procedural channels and layers.

    ``alpha_mode`` is explicit: a color alpha below one never selects
    blending by itself. ``height`` is a bump height field in meters.
    """

    id: str
    base_color: Color | ColorField = Color(0.8, 0.8, 0.8)
    roughness: float | Field = 0.5
    metallic: float | Field = 0.0
    emission_color: Color | ColorField = Color(0.0, 0.0, 0.0)
    emission_strength: float | Field = 0.0
    height: float | Field | None = None
    layers: tuple[Layer, ...] = ()
    bump_strength: float = 1.0
    alpha_mode: str = "opaque"
    double_sided: bool = False

    @property
    def needs_bake(self) -> bool:
        if self.layers:
            return True
        for name in COLOR_CHANNELS + SCALAR_CHANNELS:
            value = getattr(self, name)
            if value is not None and not is_constant(value):
                return True
        return False

    def validate(self) -> None:
        label = f"material[{self.id!r}]"
        if not isinstance(self.id, str) or not self.id or any(c.isspace() for c in self.id):
            raise ModelingError("material.id", f"{label}.id must be a nonempty string without whitespace.")
        for name in COLOR_CHANNELS:
            value = getattr(self, name)
            if not isinstance(value, (Color, ColorField)):
                raise ModelingError("material.channel", f"{label}.{name} must be a Color or color field.")
            validate_field(value, f"{label}.{name}")
        for name in SCALAR_CHANNELS:
            value = getattr(self, name)
            if value is None:
                continue
            if isinstance(value, (Color, ColorField)):
                raise ModelingError("material.channel", f"{label}.{name} must be a number or scalar field.")
            validate_field(value, f"{label}.{name}")
        for name in ("roughness", "metallic"):
            value = getattr(self, name)
            if is_constant(value) and not 0.0 <= value <= 1.0:
                raise ModelingError(f"material.{name}", f"{label}.{name} must be within 0...1.")
        if is_constant(self.emission_strength) and self.emission_strength < 0.0:
            raise ModelingError("material.emissionStrength", f"{label}.emission_strength must be nonnegative.")
        if not is_finite(self.bump_strength) or not 0.0 <= self.bump_strength <= 10.0:
            raise ModelingError("material.bumpStrength", f"{label}.bump_strength must be in 0...10.")
        if self.alpha_mode not in ALPHA_MODES:
            raise ModelingError("material.alphaMode", f"{label}.alpha_mode must be one of {ALPHA_MODES}.")
        if self.alpha_mode == "opaque" and isinstance(self.base_color, Color) and self.base_color.a != 1.0:
            raise ModelingError(
                "material.alphaMode",
                f"{label} has base_color alpha {self.base_color.a} but alpha_mode 'opaque'; choose 'blend' explicitly.",
            )
        if len(self.layers) > 16:
            raise ModelingError("material.layers", f"{label} supports at most 16 layers.")
        for index, layer in enumerate(self.layers):
            layer.validate(f"{label}.layers[{index}]")

    def to_recipe(self) -> dict:
        out: dict = {"id": self.id, "needs_bake": self.needs_bake}
        for name in COLOR_CHANNELS:
            out[name] = color_recipe(getattr(self, name))
        for name in SCALAR_CHANNELS:
            value = getattr(self, name)
            out[name] = None if value is None else scalar_recipe(value)
        out["layers"] = [layer.to_recipe() for layer in self.layers]
        out["bump_strength"] = float(self.bump_strength)
        out["alpha_mode"] = self.alpha_mode
        out["double_sided"] = bool(self.double_sided)
        return out
