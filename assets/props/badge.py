"""Name badge (24-convenience-clerk). Character accessory: real dimensions, constant materials, socket extras.

The recipe's accessories[].size_xyz_m overrides ``size`` at build time (promodeler.character.bridge).
Run:  python -m promodeler build assets/props/badge.py
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from promodeler.core import (
    Asset, AssetGenerator, Bevel, Box, Cylinder, GenerationInput, ModelingError, Part, RenderSettings, Transform,
)
from promodeler import props


@dataclass(frozen=True)
class Parameters:
    size: tuple[float, float, float] = (0.06, 0.022, 0.003)


def validate(p: Parameters) -> None:
    if len(p.size) != 3 or any(not 0.001 <= v <= 1.0 for v in p.size):
        raise ModelingError("badge.size", "size must be three values within 1 mm...1 m.")


def build(input: GenerationInput) -> Asset:
    p: Parameters = input.parameters
    w, h, d = p.size

    plastic = props.plastic("plastic", color="#F2F2EE")
    metal = props.metal()
    plate = Part(id="plate", shape=Box(size=(w, h, d)), material="plastic", transform=Transform(translation=(0.0, h / 2, 0.0)),
                 modifiers=(Bevel(width=0.001, segments=2),), smooth_angle=math.radians(50))
    clip = Part(id="clip", shape=Box(size=(w * 0.3, 0.004, 0.002)), material="metal", transform=Transform(translation=(0.0, h + 0.002, -d / 2)))
    return Asset(name="Name badge", materials=(plastic, metal), parts=(plate, clip),
                 extras=props.socket_extras("chest", (0.0, h / 2, -d / 2), "follow_bone", "pinned on the left chest, face toward +Z"))


asset = AssetGenerator(name="Name badge", parameters=Parameters(), build=build, validate=validate, seed=1)
render = RenderSettings(resolution=512, views=("perspective",))
