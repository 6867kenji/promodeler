"""M2 example: a tin can with rolled rims and a procedural rusty iron material baked to textures.

Run:  python -m promodeler build assets/rusty_can.py --views perspective,front
Quick iteration:  add --texture-resolution 256 --bake-samples 4
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from promodeler.core import (
    Asset, AssetGenerator, GenerationInput, ModelingError, Part, RenderSettings, Revolve, curves, presets,
)


@dataclass(frozen=True)
class CanParameters:
    radius: float = 0.037
    height: float = 0.11
    rust: float = 0.55


def validate(p: CanParameters) -> None:
    if not 0.02 <= p.radius <= 0.1 or not 0.03 <= p.height <= 0.3:
        raise ModelingError("can.size", "radius must be 2...10 cm and height 3...30 cm.")
    if not 0.0 <= p.rust <= 1.0:
        raise ModelingError("can.rust", "rust must be within 0...1.")


def profile(p: CanParameters):
    r, h = p.radius, p.height
    bead = 0.0022
    return curves.join(
        ((0.0, 0.002), (r - 0.004, 0.002), (r - 0.0025, 0.0)),
        curves.arc((r - bead, bead), bead, -math.pi / 2, math.pi / 2, 6),          # bottom rolled rim
        ((r - 0.0012, 2 * bead + 0.002), (r - 0.0012, h - 2 * bead - 0.002)),      # wall
        curves.arc((r - bead, h - bead), bead, -math.pi / 2, math.pi / 2, 6),      # top rolled rim
        ((r - 0.0025, h), (r - 0.004, h - 0.002), (0.0, h - 0.002)),
    )


def build(input: GenerationInput) -> Asset:
    p: CanParameters = input.parameters
    iron = presets.rusty_iron("iron", seed=input.seed, rust=p.rust)
    body = Part(
        id="body",
        shape=Revolve(profile=profile(p), segments=input.quality.curve_segments * 2),
        material="iron",
        smooth_angle=math.radians(30),
    )
    return Asset(name="Rusty can", materials=(iron,), parts=(body,))


asset = AssetGenerator(name="Rusty can", parameters=CanParameters(), build=build, validate=validate, seed=7)
render = RenderSettings(resolution=640, views=("perspective", "front"))
