"""Pure-Python asset definitions, validation and recipe serialization.

This package must stay importable without Blender. It is the vocabulary an
author (human or AI agent) writes assets in, and the contract the kernel
compiles. Conventions:

- Meters, right-handed, positive Y up, positive Z toward the viewer (glTF).
- Angles in radians. Rotations are XYZ Euler in the parent's frame.
- Colors are non-premultiplied sRGB with linear alpha.
- Parts, materials and other entities are addressed by semantic string IDs.
"""

from .asset import Asset, GenerationInput, Part, QualityProfile, RenderSettings
from .color import Color, srgb
from .diagnostics import ModelingError
from .generator import AssetGenerator
from .material import Material
from .modifiers import Bevel, Solidify, Subdivision
from .recipe import build_recipe, dump_recipe, recipe_hash
from .shapes import Box, Cone, Cylinder, Plane, Sphere
from .transform import Transform

__all__ = [
    "Asset",
    "AssetGenerator",
    "Bevel",
    "Box",
    "Color",
    "Cone",
    "Cylinder",
    "GenerationInput",
    "Material",
    "ModelingError",
    "Part",
    "Plane",
    "QualityProfile",
    "RenderSettings",
    "Solidify",
    "Sphere",
    "Subdivision",
    "Transform",
    "build_recipe",
    "dump_recipe",
    "recipe_hash",
    "srgb",
]
