"""Tote bag (23-businesswoman / 32-passerby-d). Character accessory: real dimensions, constant materials, socket extras.

The recipe's accessories[].size_xyz_m overrides ``size`` at build time (promodeler.character.bridge).
Run:  python -m promodeler build assets/props/tote.py
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
    size: tuple[float, float, float] = (0.36, 0.30, 0.11)


def validate(p: Parameters) -> None:
    if len(p.size) != 3 or any(not 0.001 <= v <= 1.0 for v in p.size):
        raise ModelingError("tote.size", "size must be three values within 1 mm...1 m.")


def build(input: GenerationInput) -> Asset:
    p: Parameters = input.parameters
    w, h, d = p.size

    canvas = props.canvas(color="#A89B86")
    body = props.rounded_box("body", (w, h, d), "canvas", bevel=0.01)
    strap_h = 0.15
    straps = tuple(props.strap(f"strap_{i}", props.arch(w * 0.25, h, strap_h, z, 12), "canvas", width=0.02, thickness=0.004)
                   for i, z in enumerate((-d * 0.35, d * 0.35)))
    return Asset(name="Tote bag", materials=(canvas,), parts=(body, *straps),
                 extras=props.socket_extras("shoulder_l", (0.0, h + strap_h, 0.0), "world_up", "straps over the shoulder or in the hand"))


asset = AssetGenerator(name="Tote bag", parameters=Parameters(), build=build, validate=validate, seed=1)
render = RenderSettings(resolution=512, views=("perspective",))
