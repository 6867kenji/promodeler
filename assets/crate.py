"""M0 example: a beveled crate with a cylindrical handle parented to the body.

Run:  python -m promodeler build assets/crate.py
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from promodeler.core import (
    Asset, AssetGenerator, Bevel, Box, Cylinder, GenerationInput, Material, ModelingError, Part,
    RenderSettings, Subdivision, Transform, srgb,
)


@dataclass(frozen=True)
class CrateParameters:
    width: float = 0.8
    height: float = 0.5
    depth: float = 0.6
    bevel: float = 0.02


def validate(p: CrateParameters) -> None:
    for name in ("width", "height", "depth"):
        if not 0.05 <= getattr(p, name) <= 5.0:
            raise ModelingError("crate.size", f"{name} must be within 0.05...5 m.")
    if not 0.0 < p.bevel < min(p.width, p.height, p.depth) / 4:
        raise ModelingError("crate.bevel", "bevel must be positive and smaller than a quarter of the smallest side.")


def build(input: GenerationInput) -> Asset:
    p: CrateParameters = input.parameters
    wood = Material("wood", base_color=srgb(0.55, 0.36, 0.20), roughness=0.75)
    iron = Material("iron", base_color=srgb(0.35, 0.35, 0.37), roughness=0.45, metallic=1.0)
    body = Part(
        id="body",
        shape=Box(size=(p.width, p.height, p.depth)),
        material="wood",
        transform=Transform(translation=(0.0, p.height / 2, 0.0)),
        modifiers=(Bevel(width=p.bevel, segments=3),),
        smooth_angle=math.radians(40),
    )
    handle = Part(
        id="handle",
        shape=Cylinder(radius=0.02, height=p.width * 0.5),
        material="iron",
        parent="body",
        # Local to the body: on top, lying along X (rotate the Y-axis cylinder about Z).
        transform=Transform(translation=(0.0, p.height / 2 + 0.05, 0.0), rotation=(0.0, 0.0, math.pi / 2)),
        modifiers=(Subdivision(levels=1),),
        smooth_angle=math.radians(60),
    )
    return Asset(name="Crate", materials=(wood, iron), parts=(body, handle))


asset = AssetGenerator(name="Crate", parameters=CrateParameters(), build=build, validate=validate, seed=1)
render = RenderSettings(resolution=512, views=("perspective",))
