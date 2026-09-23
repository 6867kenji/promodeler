"""Smartphone (25-convenience-customer). Character accessory: real dimensions, constant materials, socket extras.

The recipe's accessories[].size_xyz_m overrides ``size`` at build time (promodeler.character.bridge).
Run:  python -m promodeler build assets/props/phone.py
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
    size: tuple[float, float, float] = (0.073, 0.148, 0.009)


def validate(p: Parameters) -> None:
    if len(p.size) != 3 or any(not 0.001 <= v <= 1.0 for v in p.size):
        raise ModelingError("phone.size", "size must be three values within 1 mm...1 m.")


def build(input: GenerationInput) -> Asset:
    p: Parameters = input.parameters
    w, h, d = p.size

    body_mat = props.plastic("body", color="#22242A")
    screen = props.plastic("screen", color="#0A0B0F")
    body = Part(id="body", shape=Box(size=(w, h, d)), material="body", transform=Transform(translation=(0.0, h / 2, 0.0)),
                modifiers=(Bevel(width=0.003, segments=3),), smooth_angle=math.radians(50))
    glass = Part(id="screen", shape=Box(size=(w * 0.92, h * 0.94, 0.0006)), material="screen",
                 transform=Transform(translation=(0.0, h / 2, d / 2 + 0.0003)))
    return Asset(name="Smartphone", materials=(body_mat, screen), parts=(body, glass),
                 extras=props.socket_extras("hand_l", (0.0, h * 0.4, 0.0), "follow_bone", "held in the palm, screen toward +Z"))


asset = AssetGenerator(name="Smartphone", parameters=Parameters(), build=build, validate=validate, seed=1)
render = RenderSettings(resolution=512, views=("perspective",))
