"""Messenger bag (35-passerby-g). Character accessory: real dimensions, constant materials, socket extras.

The recipe's accessories[].size_xyz_m overrides ``size`` at build time (promodeler.character.bridge).
Run:  python -m promodeler build assets/props/messenger.py
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
    size: tuple[float, float, float] = (0.27, 0.21, 0.09)


def validate(p: Parameters) -> None:
    if len(p.size) != 3 or any(not 0.001 <= v <= 1.0 for v in p.size):
        raise ModelingError("messenger.size", "size must be three values within 1 mm...1 m.")


def build(input: GenerationInput) -> Asset:
    p: Parameters = input.parameters
    w, h, d = p.size

    nylon = props.canvas("nylon", color="#1F2124")
    body = props.rounded_box("body", (w, h, d), "nylon", bevel=0.01)
    flap = props.rounded_box("flap", (w, h * 0.55, 0.008), "nylon", bevel=0.004, translation=(0.0, h * 0.45, d / 2 + 0.004))
    strap_h = 0.5
    strap = props.strap("strap", props.arch(w * 0.45, h, strap_h, 0.0, 16), "nylon", width=0.035, thickness=0.005)
    return Asset(name="Messenger bag", materials=(nylon,), parts=(body, flap, strap),
                 extras=props.socket_extras("shoulder_l", (0.0, h + strap_h, 0.0), "world_up", "strap top rests on the shoulder"))


asset = AssetGenerator(name="Messenger bag", parameters=Parameters(), build=build, validate=validate, seed=1)
render = RenderSettings(resolution=512, views=("perspective",))
