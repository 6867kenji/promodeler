from __future__ import annotations

from dataclasses import dataclass

from .diagnostics import ModelingError, finite_vector


@dataclass(frozen=True)
class Transform:
    """Parent-local TRS in authoring space (Y up).

    ``rotation`` is XYZ Euler in radians. Scale components must be positive;
    mirroring is a modeling operation, not a transform, so that winding and
    normals stay explicit.
    """

    translation: tuple[float, float, float] = (0.0, 0.0, 0.0)
    rotation: tuple[float, float, float] = (0.0, 0.0, 0.0)
    scale: tuple[float, float, float] = (1.0, 1.0, 1.0)

    def validate(self, label: str = "transform") -> None:
        finite_vector(self.translation, 3, "transform.translation", f"{label}.translation")
        finite_vector(self.rotation, 3, "transform.rotation", f"{label}.rotation")
        scale = finite_vector(self.scale, 3, "transform.scale", f"{label}.scale")
        if min(scale) <= 0.0:
            raise ModelingError("transform.scale", f"{label}.scale components must be positive, got {scale}.")

    def to_recipe(self) -> dict:
        return {
            "translation": [float(v) for v in self.translation],
            "rotation": [float(v) for v in self.rotation],
            "scale": [float(v) for v in self.scale],
        }


IDENTITY = Transform()
