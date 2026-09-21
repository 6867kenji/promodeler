from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from .diagnostics import ModelingError, is_finite
from .material import Material
from .modifiers import Modifier
from .shapes import Shape
from .transform import Transform

RENDER_ENGINES = ("eevee", "cycles")
RENDER_VIEWS = ("perspective", "front", "side", "top")
RENDER_PASSES = ("shaded", "clay", "wireframe", "normals", "uv")
RENDER_ENVIRONMENTS = ("studio", "overcast", "sunny", "sunset")


@dataclass(frozen=True)
class QualityProfile:
    """Tessellation defaults and budgets. Lower values regenerate the same recipe as a coarser LOD."""

    curve_segments: int = 32
    surface_segments: int = 16
    max_triangles: int = 2_000_000
    texture_resolution: int = 1024
    bake_samples: int = 32

    def validate(self) -> None:
        for name, minimum in (("curve_segments", 3), ("surface_segments", 2), ("max_triangles", 1),
                              ("texture_resolution", 16), ("bake_samples", 1)):
            value = getattr(self, name)
            if not isinstance(value, int) or value < minimum:
                raise ModelingError("quality.range", f"quality.{name} must be an integer >= {minimum}.")
        if self.texture_resolution > 8192 or self.bake_samples > 4096:
            raise ModelingError("quality.range", "quality.texture_resolution <= 8192 and bake_samples <= 4096.")

    def to_recipe(self) -> dict:
        return {
            "curve_segments": self.curve_segments,
            "surface_segments": self.surface_segments,
            "max_triangles": self.max_triangles,
            "texture_resolution": self.texture_resolution,
            "bake_samples": self.bake_samples,
        }


@dataclass(frozen=True)
class RenderSettings:
    """Verification render options. They never affect the exported asset."""

    resolution: int = 512
    engine: str = "eevee"
    views: tuple[str, ...] = ("perspective",)
    passes: tuple[str, ...] = ("shaded",)
    environment: str = "studio"
    samples: int = 16
    background: tuple[float, float, float] = (0.35, 0.35, 0.35)

    def validate(self) -> None:
        if not self.passes or any(p not in RENDER_PASSES for p in self.passes):
            raise ModelingError("render.passes", f"render.passes must be nonempty and within {RENDER_PASSES}.")
        if self.environment not in RENDER_ENVIRONMENTS and not self.environment.lower().endswith((".hdr", ".exr")):
            raise ModelingError("render.environment", f"render.environment must be one of {RENDER_ENVIRONMENTS} or an .hdr/.exr path.")
        if not isinstance(self.resolution, int) or not 64 <= self.resolution <= 4096:
            raise ModelingError("render.resolution", "render.resolution must be an integer in 64...4096.")
        if self.engine not in RENDER_ENGINES:
            raise ModelingError("render.engine", f"render.engine must be one of {RENDER_ENGINES}.")
        if not self.views or any(v not in RENDER_VIEWS for v in self.views):
            raise ModelingError("render.views", f"render.views must be nonempty and within {RENDER_VIEWS}.")
        if not isinstance(self.samples, int) or not 1 <= self.samples <= 4096:
            raise ModelingError("render.samples", "render.samples must be an integer in 1...4096.")
        if len(self.background) != 3 or any(not is_finite(v) or not 0 <= v <= 1 for v in self.background):
            raise ModelingError("render.background", "render.background must be three values in 0...1.")

    def to_recipe(self) -> dict:
        return {
            "resolution": self.resolution,
            "engine": self.engine,
            "views": list(self.views),
            "passes": list(self.passes),
            "environment": self.environment,
            "samples": self.samples,
            "background": [float(v) for v in self.background],
        }


@dataclass(frozen=True)
class Part:
    """A semantic, independently addressable piece of the asset.

    ``smooth_angle`` of ``None`` keeps flat shading. Otherwise faces meeting
    at an angle below it are shaded smooth and sharper edges stay hard.
    """

    id: str
    shape: Shape
    material: str
    transform: Transform = Transform()
    modifiers: tuple[Modifier, ...] = ()
    parent: str | None = None
    smooth_angle: float | None = None

    def validate(self) -> None:
        label = f"part[{self.id!r}]"
        if not isinstance(self.id, str) or not self.id or any(c.isspace() for c in self.id):
            raise ModelingError("part.id", f"{label}.id must be a nonempty string without whitespace.")
        if self.id == "root":
            raise ModelingError("part.id", "'root' is reserved for the asset root.")
        self.shape.validate(f"{label}.shape")
        self.transform.validate(f"{label}.transform")
        for index, modifier in enumerate(self.modifiers):
            modifier.validate(f"{label}.modifiers[{index}]")
        if self.smooth_angle is not None:
            if not is_finite(self.smooth_angle) or not 0.0 <= self.smooth_angle <= math.pi:
                raise ModelingError("part.smoothAngle", f"{label}.smooth_angle must be in 0...pi radians.")

    def to_recipe(self) -> dict:
        return {
            "id": self.id,
            "shape": self.shape.to_recipe(),
            "material": self.material,
            "transform": self.transform.to_recipe(),
            "modifiers": [m.to_recipe() for m in self.modifiers],
            "parent": self.parent,
            "smooth_angle": None if self.smooth_angle is None else float(self.smooth_angle),
        }


@dataclass(frozen=True)
class Asset:
    name: str
    materials: tuple[Material, ...]
    parts: tuple[Part, ...]

    def validate(self) -> None:
        if not isinstance(self.name, str) or not self.name.strip():
            raise ModelingError("asset.name", "asset.name must be a nonempty string.")
        if not self.parts:
            raise ModelingError("asset.parts", "An asset needs at least one part.")
        material_ids: set[str] = set()
        for material in self.materials:
            material.validate()
            if material.id in material_ids:
                raise ModelingError("material.duplicateID", f"Material id {material.id!r} is defined twice.")
            material_ids.add(material.id)
        part_ids: set[str] = set()
        for part in self.parts:
            part.validate()
            if part.id in part_ids:
                raise ModelingError("part.duplicateID", f"Part id {part.id!r} is defined twice.")
            part_ids.add(part.id)
            if part.material not in material_ids:
                raise ModelingError("part.material", f"Part {part.id!r} references unknown material {part.material!r}.")
        parents = {part.id: part.parent for part in self.parts}
        for part in self.parts:
            if part.parent is not None and part.parent not in part_ids:
                raise ModelingError("part.parent", f"Part {part.id!r} references unknown parent {part.parent!r}.")
            seen = {part.id}
            current = part.parent
            while current is not None:
                if current in seen:
                    raise ModelingError("part.parentCycle", f"Part {part.id!r} has a parent cycle.")
                seen.add(current)
                current = parents[current]

    def part(self, part_id: str) -> Part:
        for part in self.parts:
            if part.id == part_id:
                return part
        raise KeyError(part_id)

    def to_recipe(self) -> dict:
        return {
            "name": self.name,
            "materials": [m.to_recipe() for m in self.materials],
            "parts": [p.to_recipe() for p in self.parts],
        }


@dataclass(frozen=True)
class GenerationInput:
    parameters: Any
    seed: int = 0
    quality: QualityProfile = field(default_factory=QualityProfile)
