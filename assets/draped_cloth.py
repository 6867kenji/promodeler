"""M5 example: a cloth sheet dropped over a wooden block and frozen after the simulation settles.

Run:  python -m promodeler build assets/draped_cloth.py
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from promodeler.core import (
    Asset, AssetGenerator, Bevel, Box, ClothDrape, GenerationInput, Material, ModelingError, Noise, Part, Plane,
    RenderSettings, Solidify, Subdivision, Transform, presets, srgb,
)


@dataclass(frozen=True)
class DrapeParameters:
    sheet: float = 0.5
    block: float = 0.2
    frames: int = 70


def validate(p: DrapeParameters) -> None:
    if not 0.2 <= p.sheet <= 2.0 or not 0.05 <= p.block <= 1.0:
        raise ModelingError("drape.size", "sheet must be 0.2...2 m and block 5 cm...1 m.")
    if not 10 <= p.frames <= 300:
        raise ModelingError("drape.frames", "frames must be 10...300.")


def build(input: GenerationInput) -> Asset:
    p: DrapeParameters = input.parameters
    wood = presets.old_wood("wood", seed=input.seed, weathering=0.3)
    fabric = Material("fabric", base_color=srgb(0.62, 0.2, 0.18), roughness=0.9 - Noise(size=0.01, seed=input.seed) * 0.15,
                      height=Noise(size=(0.004, 0.0008, 0.004), detail=3.0, seed=input.seed + 1) * 0.0001, bump_strength=1.5)
    block = Part(
        id="block",
        shape=Box(size=(p.block, p.block * 0.8, p.block)),
        material="wood",
        transform=Transform(translation=(0.0, p.block * 0.4, 0.0)),
        modifiers=(Bevel(width=0.006, segments=3),),
        smooth_angle=math.radians(40),
    )
    sheet = Part(
        id="sheet",
        shape=Plane(size=(p.sheet, p.sheet)),
        material="fabric",
        transform=Transform(translation=(0.0, p.block * 0.8 + 0.06, 0.0), rotation=(0.0, math.radians(20), 0.0)),
        modifiers=(
            Subdivision(levels=5, smooth=False),
            ClothDrape(frames=p.frames, mass=0.25, stiffness=12.0, bending=0.15, damping=6.0, quality=6, thickness=0.004),
            Solidify(thickness=0.002, offset=0.0),
        ),
        smooth_angle=math.radians(60),
    )
    return Asset(name="Draped cloth", materials=(wood, fabric), parts=(block, sheet))


asset = AssetGenerator(name="Draped cloth", parameters=DrapeParameters(), build=build, validate=validate, seed=5)
render = RenderSettings(resolution=640, views=("perspective", "front"), passes=("shaded", "clay"))
