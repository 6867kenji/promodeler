"""M2/M3 example: a dented tin can with rolled rims and a procedural rusty iron material baked to textures.

The revolve profile carries extra wall points and a plain subdivision so
the dents and wobble from ``imperfections`` have vertices to move.

Run:  python -m promodeler build assets/rusty_can.py
Quick iteration:  add --texture-resolution 256 --bake-samples 4 --passes shaded
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from promodeler.core import (
    Asset, AssetGenerator, Displace, GenerationInput, ModelingError, Part, RenderSettings, Revolve, Subdivision,
    curves, imperfections, presets,
)


@dataclass(frozen=True)
class CanParameters:
    radius: float = 0.037
    height: float = 0.11
    rust: float = 0.55
    dents: float = 1.0


def validate(p: CanParameters) -> None:
    if not 0.02 <= p.radius <= 0.1 or not 0.03 <= p.height <= 0.3:
        raise ModelingError("can.size", "radius must be 2...10 cm and height 3...30 cm.")
    if not 0.0 <= p.rust <= 1.0:
        raise ModelingError("can.rust", "rust must be within 0...1.")
    if not 0.0 <= p.dents <= 2.0:
        raise ModelingError("can.dents", "dents must be within 0...2.")


def profile(p: CanParameters):
    r, h = p.radius, p.height
    bead = 0.0022
    wall_bottom = 2 * bead + 0.002
    wall_top = h - 2 * bead - 0.002
    wall = tuple((r - 0.0012, wall_bottom + (wall_top - wall_bottom) * i / 20) for i in range(21))
    return curves.join(
        ((0.0, 0.002), (r - 0.004, 0.002), (r - 0.0025, 0.0)),
        curves.arc((r - bead, bead), bead, -math.pi / 2, math.pi / 2, 6),          # bottom rolled rim
        wall,
        curves.arc((r - bead, h - bead), bead, -math.pi / 2, math.pi / 2, 6),      # top rolled rim
        ((r - 0.0025, h), (r - 0.004, h - 0.002), (0.0, h - 0.002)),
    )


def build(input: GenerationInput) -> Asset:
    p: CanParameters = input.parameters
    iron = presets.rusty_iron("iron", seed=input.seed, rust=p.rust)
    modifiers = ()
    if p.dents > 0:
        shape_noise = (
            imperfections.dents(size=p.radius * 1.1, depth=0.0035 * p.dents, coverage=0.3, seed=input.seed)
            + imperfections.wobble(size=p.height, amplitude=0.0008 * p.dents, seed=input.seed + 1)
        )
        modifiers = (Subdivision(levels=1, smooth=False), Displace(height=shape_noise))
    body = Part(
        id="body",
        shape=Revolve(profile=profile(p), segments=input.quality.curve_segments * 2),
        material="iron",
        modifiers=modifiers,
        smooth_angle=math.radians(30),
    )
    return Asset(name="Rusty can", materials=(iron,), parts=(body,))


asset = AssetGenerator(name="Rusty can", parameters=CanParameters(), build=build, validate=validate, seed=7)
render = RenderSettings(resolution=640, views=("perspective", "front"), passes=("shaded", "clay", "wireframe"),
                        environment="studio")
