"""Briefcase (22-businessman). Character accessory: real dimensions, constant materials, socket extras.

The recipe's accessories[].size_xyz_m overrides ``size`` at build time (promodeler.character.bridge).
Run:  python -m promodeler build assets/props/briefcase.py
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
    size: tuple[float, float, float] = (0.40, 0.29, 0.07)


def validate(p: Parameters) -> None:
    if len(p.size) != 3 or any(not 0.001 <= v <= 1.0 for v in p.size):
        raise ModelingError("briefcase.size", "size must be three values within 1 mm...1 m.")


def build(input: GenerationInput) -> Asset:
    p: Parameters = input.parameters
    w, h, d = p.size

    leather = props.leather(color="#302C29")
    metal = props.metal()
    body = props.rounded_box("body", (w, h, d), "leather", bevel=0.008)
    handle_h = 0.10
    handle = props.cord("handle", props.arch(0.07, h, handle_h * 0.85, segments=12), "leather", radius=0.007)
    zips = tuple(Part(id=f"zip_{i}", shape=Box(size=(w * 0.92, 0.004, 0.003)), material="metal",
                      transform=Transform(translation=(0.0, h + 0.002, z))) for i, z in enumerate((-d * 0.2, d * 0.2)))
    return Asset(name="Briefcase", materials=(leather, metal), parts=(body, handle, *zips),
                 extras=props.socket_extras("hand_r", (0.0, h + handle_h * 0.85, 0.0), "world_up", "held by the handle, hangs vertically"))


asset = AssetGenerator(name="Briefcase", parameters=Parameters(), build=build, validate=validate, seed=1)
render = RenderSettings(resolution=512, views=("perspective",))
