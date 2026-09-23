"""Wristwatch (31-passerby-c). Character accessory: real dimensions, constant materials, socket extras.

The recipe's accessories[].size_xyz_m overrides ``size`` at build time (promodeler.character.bridge).
Run:  python -m promodeler build assets/props/watch.py
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from promodeler.core import (
    Asset, AssetGenerator, Bevel, Box, Cylinder, GenerationInput, ModelingError, Part, RenderSettings, Revolve, Transform, curves,
)
from promodeler import props


@dataclass(frozen=True)
class Parameters:
    size: tuple[float, float, float] = (0.04, 0.01, 0.04)


def validate(p: Parameters) -> None:
    if len(p.size) != 3 or any(not 0.001 <= v <= 1.0 for v in p.size):
        raise ModelingError("watch.size", "size must be three values within 1 mm...1 m.")


def build(input: GenerationInput) -> Asset:
    p: Parameters = input.parameters
    w, h, d = p.size

    metal = props.metal()
    face = props.plastic("face", color="#F2F0EA")
    case = Part(id="case", shape=Cylinder(radius=w / 2, height=h, segments=32), material="metal",
                transform=Transform(translation=(0.0, 0.03 + h / 2, 0.0)), modifiers=(Bevel(width=0.001, segments=2),), smooth_angle=math.radians(60))
    dial = Part(id="dial", shape=Cylinder(radius=w / 2 - 0.003, height=0.001, segments=32), material="face",
                transform=Transform(translation=(0.0, 0.03 + h + 0.0005, 0.0)), smooth_angle=math.radians(60))
    # Band: a seamless torus with a rectangular section around the wrist axis (X), revolved about Y and tipped.
    section = tuple((0.03 + 0.0015 + u, v) for u, v in curves.rect(0.003, 0.02)) + ((0.03 + 0.0015 - 0.0015, -0.01),)
    band = Part(id="band", shape=Revolve(profile=section, segments=32, cap_ends=False), material="metal",
                transform=Transform(translation=(0.0, 0.03, 0.0), rotation=(0.0, 0.0, math.pi / 2)), smooth_angle=math.radians(40))
    return Asset(name="Wristwatch", materials=(metal, face), parts=(case, dial, band),
                 extras=props.socket_extras("wrist_l", (0.0, 0.03, 0.0), "follow_bone", "band centre on the wrist axis; dial faces +Y"))


asset = AssetGenerator(name="Wristwatch", parameters=Parameters(), build=build, validate=validate, seed=1)
render = RenderSettings(resolution=512, views=("perspective",))
