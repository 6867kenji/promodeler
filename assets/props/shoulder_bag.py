"""Shoulder bag (30-passerby-b). Character accessory: real dimensions, constant materials, socket extras.

The recipe's accessories[].size_xyz_m overrides ``size`` at build time (promodeler.character.bridge).
Run:  python -m promodeler build assets/props/shoulder_bag.py
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
    size: tuple[float, float, float] = (0.23, 0.18, 0.07)


def validate(p: Parameters) -> None:
    if len(p.size) != 3 or any(not 0.001 <= v <= 1.0 for v in p.size):
        raise ModelingError("shoulder_bag.size", "size must be three values within 1 mm...1 m.")


def build(input: GenerationInput) -> Asset:
    p: Parameters = input.parameters
    w, h, d = p.size

    leather = props.leather(color="#6B4A2E")
    body = props.rounded_box("body", (w, h, d), "leather", bevel=0.008)
    flap = props.rounded_box("flap", (w * 0.98, h * 0.5, 0.006), "leather", bevel=0.003, translation=(0.0, h * 0.5, d / 2 + 0.003))
    strap_h = 0.45
    strap = props.strap("strap", props.arch(w * 0.45, h, strap_h, 0.0, 16), "leather", width=0.018, thickness=0.004)
    return Asset(name="Shoulder bag", materials=(leather,), parts=(body, flap, strap),
                 extras=props.socket_extras("shoulder_l", (0.0, h + strap_h, 0.0), "world_up", "strap top rests on the shoulder"))


asset = AssetGenerator(name="Shoulder bag", parameters=Parameters(), build=build, validate=validate, seed=1)
render = RenderSettings(resolution=512, views=("perspective",))
