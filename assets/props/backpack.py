"""Backpack (29-passerby-a). Character accessory: real dimensions, constant materials, socket extras.

The recipe's accessories[].size_xyz_m overrides ``size`` at build time (promodeler.character.bridge).
Run:  python -m promodeler build assets/props/backpack.py
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
    size: tuple[float, float, float] = (0.30, 0.43, 0.15)


def validate(p: Parameters) -> None:
    if len(p.size) != 3 or any(not 0.001 <= v <= 1.0 for v in p.size):
        raise ModelingError("backpack.size", "size must be three values within 1 mm...1 m.")


def build(input: GenerationInput) -> Asset:
    p: Parameters = input.parameters
    w, h, d = p.size

    nylon = props.canvas("nylon", color="#243247")
    body = props.rounded_box("body", (w, h * 0.85, d), "nylon", bevel=0.02)
    lid = props.rounded_box("lid", (w * 0.96, h * 0.15, d * 0.9), "nylon", bevel=0.015, translation=(0.0, h * 0.85, 0.0))
    strap_w = 0.055
    straps = tuple(props.strap(f"strap_{i}", ((x, h * 0.9, -d / 2), (x, h * 0.55, -d / 2 - 0.04), (x, h * 0.15, -d / 2 - 0.02), (x, 0.02, -d / 2)),
                               "nylon", width=strap_w, thickness=0.008) for i, x in enumerate((-w * 0.25, w * 0.25)))
    return Asset(name="Backpack", materials=(nylon,), parts=(body, lid, *straps),
                 extras=props.socket_extras("back", (0.0, h * 0.75, -d / 2), "follow_bone", "straps face the back; grip point is the strap attachment"))


asset = AssetGenerator(name="Backpack", parameters=Parameters(), build=build, validate=validate, seed=1)
render = RenderSettings(resolution=512, views=("perspective",))
