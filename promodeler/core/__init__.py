"""Pure-Python asset definitions, validation and recipe serialization.

This package must stay importable without Blender. It is the vocabulary an
author (human or AI agent) writes assets in, and the contract the kernel
compiles. Conventions:

- Meters, right-handed, positive Y up, positive Z toward the viewer (glTF).
- Angles in radians. Rotations are XYZ Euler in the parent's frame.
- Colors are non-premultiplied sRGB with linear alpha.
- Parts, materials and other entities are addressed by semantic string IDs.
"""

from . import curves, imperfections, presets
from .asset import Asset, GenerationInput, Part, QualityProfile, RenderSettings
from .color import Color, srgb
from .diagnostics import ModelingError
from .fields import (
    AmbientOcclusion, Cavity, ColorField, ColorMix, ColorRamp, Curvature, Facing, Field, Mix, Noise, Position,
    Thickness, Voronoi,
)
from .generator import AssetGenerator
from .material import Layer, Material
from .modifiers import Array, Bevel, Boolean, Cutter, Displace, Mirror, SimpleDeform, Solidify, Subdivision
from .profile import Profile
from .recipe import build_recipe, dump_recipe, recipe_hash
from .shapes import Box, Cone, Cylinder, Extrude, Loft, LoftSection, Plane, Revolve, Sphere, Sweep
from .transform import Transform

__all__ = [
    "AmbientOcclusion",
    "Array",
    "Asset",
    "AssetGenerator",
    "Bevel",
    "Boolean",
    "Box",
    "Cavity",
    "Color",
    "ColorField",
    "ColorMix",
    "ColorRamp",
    "Cone",
    "Curvature",
    "Cutter",
    "Cylinder",
    "Displace",
    "Extrude",
    "Facing",
    "Field",
    "GenerationInput",
    "Layer",
    "Loft",
    "LoftSection",
    "Material",
    "Mirror",
    "Mix",
    "ModelingError",
    "Part",
    "Noise",
    "Plane",
    "Position",
    "Profile",
    "QualityProfile",
    "RenderSettings",
    "Revolve",
    "SimpleDeform",
    "Solidify",
    "Sphere",
    "Subdivision",
    "Sweep",
    "Thickness",
    "Transform",
    "Voronoi",
    "build_recipe",
    "curves",
    "dump_recipe",
    "imperfections",
    "presets",
    "recipe_hash",
    "srgb",
]
