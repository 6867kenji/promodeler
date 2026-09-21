"""M1 example: a ceramic mug. Revolve for the body, sweep for the handle, exact union to fuse them.

Run:  python -m promodeler build assets/mug.py --views perspective,front
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from promodeler.core import (
    Asset, AssetGenerator, Bevel, Boolean, Cutter, GenerationInput, Material, ModelingError, Part, Profile,
    RenderSettings, Revolve, Sweep, Transform, curves, srgb,
)


@dataclass(frozen=True)
class MugParameters:
    radius: float = 0.04
    height: float = 0.095
    wall: float = 0.004
    handle_thickness: float = 0.007


def validate(p: MugParameters) -> None:
    if not 0.02 <= p.radius <= 0.1 or not 0.04 <= p.height <= 0.2:
        raise ModelingError("mug.size", "radius must be 2...10 cm and height 4...20 cm.")
    if not 0.002 <= p.wall <= p.radius / 3:
        raise ModelingError("mug.wall", "wall must be at least 2 mm and under a third of the radius.")
    if not 0.004 <= p.handle_thickness <= 0.015:
        raise ModelingError("mug.handle", "handle_thickness must be 4...15 mm.")


def body_profile(p: MugParameters):
    """(radius, height) from the outer bottom center up the outside, over the rim, down the inside."""
    r, h, w = p.radius, p.height, p.wall
    rim = w / 2
    foot = 0.004
    outside = curves.join(
        ((0.0, 0.0), (r - foot, 0.0)),
        curves.arc((r - foot, foot), foot, -math.pi / 2, 0.0, 4),          # rounded foot
        ((r, h - rim),),
        curves.arc((r - rim, h - rim), rim, 0.0, math.pi, 8),               # rounded rim
        ((r - w, w + 0.002),),
        curves.arc((r - w - 0.002, w + 0.002), 0.002, 0.0, -math.pi / 2, 3),  # inner floor fillet
        ((0.0, w),),
    )
    return outside


def handle_path(p: MugParameters):
    r, h = p.radius, p.height
    top = (r - 0.002, h * 0.78, 0.0)
    bottom = (r - 0.002, h * 0.22, 0.0)
    reach = r + h * 0.42
    return curves.bezier(top, (reach, h * 0.95, 0.0), (reach, h * 0.05, 0.0), bottom, 40)


def build(input: GenerationInput) -> Asset:
    p: MugParameters = input.parameters
    glaze = Material("glaze", base_color=srgb(0.92, 0.90, 0.85), roughness=0.18)
    t = p.handle_thickness
    handle = Cutter(
        shape=Sweep(
            profile=Profile(curves.rounded_rect(t, t * 1.6, t * 0.35, 3)),
            path=handle_path(p),
            capped=True,
        ),
    )
    body = Part(
        id="body",
        shape=Revolve(profile=body_profile(p), segments=input.quality.curve_segments * 2),
        material="glaze",
        modifiers=(Boolean("union", cutter=handle),),
        smooth_angle=math.radians(35),
    )
    return Asset(name="Mug", materials=(glaze,), parts=(body,))


asset = AssetGenerator(name="Mug", parameters=MugParameters(), build=build, validate=validate, seed=1)
render = RenderSettings(resolution=512, views=("perspective", "front"))
