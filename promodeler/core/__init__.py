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
from .asset import LOD, Asset, ExportSettings, GenerationInput, Part, QualityProfile, RenderSettings
from .color import Color, srgb
from .diagnostics import ModelingError
from .fields import (
    AmbientOcclusion, Cavity, ColorField, ColorMix, ColorRamp, Curvature, Facing, Field, Mix, Noise, Position,
    Thickness, Voronoi,
)
from .generator import AssetGenerator
from .material import Layer, Material
from .modifiers import Array, Bevel, Boolean, ClothDrape, Cutter, Displace, Mirror, SimpleDeform, Solidify, Subdivision
from .rig import Clip, Joint, JointTransform, Keyframe, Pose, Rig
from .profile import Profile
from .recipe import build_recipe, dump_recipe, recipe_hash
from .shapes import Box, Cone, Cylinder, Extrude, Fur, Loft, LoftSection, Plane, Revolve, Scatter, Sphere, Sweep
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
    "Clip",
    "ClothDrape",
    "Color",
    "ColorField",
    "ColorMix",
    "ColorRamp",
    "Cone",
    "Curvature",
    "Cutter",
    "Cylinder",
    "Displace",
    "ExportSettings",
    "Extrude",
    "Facing",
    "Field",
    "Fur",
    "GenerationInput",
    "Joint",
    "JointTransform",
    "Keyframe",
    "LOD",
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
    "Pose",
    "Position",
    "Profile",
    "QualityProfile",
    "RenderSettings",
    "Revolve",
    "Rig",
    "Scatter",
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
