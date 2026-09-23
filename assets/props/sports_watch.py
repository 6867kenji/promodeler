"""Sports watch (34-passerby-f). Character accessory: real dimensions, constant materials, socket extras.

The recipe's accessories[].size_xyz_m overrides ``size`` at build time (promodeler.character.bridge).
Run:  python -m promodeler build assets/props/sports_watch.py
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
    size: tuple[float, float, float] = (0.038, 0.012, 0.042)


def validate(p: Parameters) -> None:
    if len(p.size) != 3 or any(not 0.001 <= v <= 1.0 for v in p.size):
        raise ModelingError("sports_watch.size", "size must be three values within 1 mm...1 m.")


def build(input: GenerationInput) -> Asset:
    p: Parameters = input.parameters
    w, h, d = p.size

    resin = props.plastic("resin", color="#2B2D31")
    face = props.plastic("face", color="#111111")
    case = Part(id="case", shape=Box(size=(w, h, d)), material="resin", transform=Transform(translation=(0.0, 0.03 + h / 2, 0.0)),
                modifiers=(Bevel(width=0.004, segments=3),), smooth_angle=math.radians(50))
    dial = Part(id="dial", shape=Box(size=(w * 0.7, 0.001, d * 0.7)), material="face", transform=Transform(translation=(0.0, 0.03 + h + 0.0005, 0.0)))
    # Band: a seamless torus with a rectangular section around the wrist axis (X), revolved about Y and tipped.
    section = tuple((0.03 + 0.0015 + u, v) for u, v in curves.rect(0.003, 0.02)) + ((0.03 + 0.0015 - 0.0015, -0.01),)
    band = Part(id="band", shape=Revolve(profile=section, segments=32, cap_ends=False), material="resin",
                transform=Transform(translation=(0.0, 0.03, 0.0), rotation=(0.0, 0.0, math.pi / 2)), smooth_angle=math.radians(40))
    return Asset(name="Sports watch", materials=(resin, face), parts=(case, dial, band),
                 extras=props.socket_extras("wrist_l", (0.0, 0.03, 0.0), "follow_bone", "band centre on the wrist axis; dial faces +Y"))


asset = AssetGenerator(name="Sports watch", parameters=Parameters(), build=build, validate=validate, seed=1)
render = RenderSettings(resolution=512, views=("perspective",))
