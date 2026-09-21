"""M2 example: a closed leather journal. Simple geometry; the worn leather material carries the realism.

Run:  python -m promodeler build assets/leather_journal.py --views perspective,top
Quick iteration:  add --texture-resolution 256 --bake-samples 4
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from promodeler.core import (
    Asset, AssetGenerator, Bevel, Box, Extrude, GenerationInput, Material, ModelingError, Part, Profile,
    RenderSettings, Subdivision, Transform, curves, presets, srgb,
)


@dataclass(frozen=True)
class JournalParameters:
    width: float = 0.15
    length: float = 0.21
    cover: float = 0.005
    pages: float = 0.028
    wear: float = 1.0


def validate(p: JournalParameters) -> None:
    if not 0.05 <= p.width <= 0.5 or not 0.05 <= p.length <= 0.6:
        raise ModelingError("journal.size", "width and length must be 5...60 cm.")
    if not 0.002 <= p.cover <= 0.02 or not 0.005 <= p.pages <= 0.1:
        raise ModelingError("journal.thickness", "cover must be 2...20 mm and pages 5...100 mm.")
    if not 0.0 <= p.wear <= 2.0:
        raise ModelingError("journal.wear", "wear must be within 0...2.")


def build(input: GenerationInput) -> Asset:
    p: JournalParameters = input.parameters
    leather = presets.worn_leather("leather", color=srgb(0.34, 0.19, 0.10), seed=input.seed, wear=p.wear)
    paper = Material("paper", base_color=srgb(0.88, 0.85, 0.78), roughness=0.9)
    cover_profile = Profile(curves.rounded_rect(p.width, p.length, 0.008, 6))

    def cover(part_id: str, y: float) -> Part:
        return Part(
            id=part_id,
            shape=Extrude(profile=cover_profile, depth=p.cover, axis="y"),
            material="leather",
            transform=Transform(translation=(0.0, y, 0.0)),
            modifiers=(Bevel(width=p.cover * 0.3, segments=3, angle_limit=math.radians(60)),),
            smooth_angle=math.radians(40),
        )

    block = Part(
        id="pages",
        shape=Box(size=(p.width - 0.012, p.pages, p.length - 0.012)),
        material="paper",
        transform=Transform(translation=(0.004, p.cover + p.pages / 2, 0.0)),
        modifiers=(Bevel(width=0.0008, segments=2),),
        smooth_angle=math.radians(40),
    )
    return Asset(
        name="Leather journal",
        materials=(leather, paper),
        parts=(cover("front_cover", p.cover + p.pages), block, cover("back_cover", 0.0)),
    )


asset = AssetGenerator(name="Leather journal", parameters=JournalParameters(), build=build, validate=validate, seed=3)
render = RenderSettings(resolution=640, views=("perspective", "top"))
