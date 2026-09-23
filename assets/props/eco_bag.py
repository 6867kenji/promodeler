"""Eco bag (25-convenience-customer). Character accessory: real dimensions, constant materials, socket extras.

The recipe's accessories[].size_xyz_m overrides ``size`` at build time (promodeler.character.bridge).
Run:  python -m promodeler build assets/props/eco_bag.py
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
    size: tuple[float, float, float] = (0.34, 0.38, 0.12)


def validate(p: Parameters) -> None:
    if len(p.size) != 3 or any(not 0.001 <= v <= 1.0 for v in p.size):
        raise ModelingError("eco_bag.size", "size must be three values within 1 mm...1 m.")


def build(input: GenerationInput) -> Asset:
    p: Parameters = input.parameters
    w, h, d = p.size

    canvas = props.canvas(color="#E6DECB")
    body = props.rounded_box("body", (w, h * 0.72, d), "canvas", bevel=0.012)
    strap_h = h * 0.28
    straps = tuple(props.strap(f"strap_{i}", props.arch(w * 0.28, h * 0.72, strap_h, z, 12), "canvas", width=0.025, thickness=0.003)
                   for i, z in enumerate((-d * 0.3, d * 0.3)))
    return Asset(name="Eco bag", materials=(canvas,), parts=(body, *straps),
                 extras=props.socket_extras("hand_l", (0.0, h, 0.0), "world_up", "carried by the handles"))


asset = AssetGenerator(name="Eco bag", parameters=Parameters(), build=build, validate=validate, seed=1)
render = RenderSettings(resolution=512, views=("perspective",))
