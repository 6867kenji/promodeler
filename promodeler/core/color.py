from __future__ import annotations

from dataclasses import dataclass

from .diagnostics import ModelingError, is_finite


@dataclass(frozen=True)
class Color:
    """Non-premultiplied sRGB-encoded RGB in 0...1 with linear alpha."""

    r: float
    g: float
    b: float
    a: float = 1.0

    def validate(self, label: str = "color") -> None:
        for name, value in (("r", self.r), ("g", self.g), ("b", self.b), ("a", self.a)):
            if not is_finite(value) or not 0.0 <= value <= 1.0:
                raise ModelingError("color.range", f"{label}.{name} must be finite and within 0...1, got {value!r}.")

    def to_linear(self) -> tuple[float, float, float, float]:
        """Linear-light RGB plus unchanged alpha, for renderer uniforms."""
        return (_decode(self.r), _decode(self.g), _decode(self.b), self.a)

    def to_recipe(self) -> list[float]:
        return [self.r, self.g, self.b, self.a]

    def scaled(self, factor: float) -> "Color":
        """Brighten or darken in linear light, clamped to 0...1, keeping alpha."""
        r, g, b, a = self.to_linear()
        return Color.from_linear(r * factor, g * factor, b * factor, a)

    @staticmethod
    def from_linear(r: float, g: float, b: float, a: float = 1.0) -> "Color":
        return Color(_encode(r), _encode(g), _encode(b), a)


def srgb(r: float, g: float, b: float, a: float = 1.0) -> Color:
    return Color(float(r), float(g), float(b), float(a))


def _decode(x: float) -> float:
    return x / 12.92 if x <= 0.04045 else ((x + 0.055) / 1.055) ** 2.4


def _encode(x: float) -> float:
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    return 12.92 * x if x <= 0.0031308 else 1.055 * x ** (1 / 2.4) - 0.055
