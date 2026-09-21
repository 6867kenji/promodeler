"""M1 example: an open-end wrench.

Profile extrusion with a hexagonal hanging hole, edge bevel, then grip
grooves cut by an arrayed cylinder with the exact boolean solver.

Run:  python -m promodeler build assets/wrench.py --views perspective,top
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from promodeler.core import (
    Array, Asset, AssetGenerator, Bevel, Boolean, Cutter, Cylinder, Extrude, GenerationInput, Material,
    ModelingError, Part, Profile, RenderSettings, Transform, curves, srgb,
)


@dataclass(frozen=True)
class WrenchParameters:
    length: float = 0.18
    thickness: float = 0.006
    jaw_width: float = 0.013
    head_radius: float = 0.016
    grip_grooves: int = 5


def validate(p: WrenchParameters) -> None:
    if not 0.08 <= p.length <= 0.4:
        raise ModelingError("wrench.length", "length must be 8...40 cm.")
    if not 0.003 <= p.thickness <= 0.02:
        raise ModelingError("wrench.thickness", "thickness must be 3...20 mm.")
    if not p.jaw_width < p.head_radius * 1.4:
        raise ModelingError("wrench.jaw", "jaw_width must be smaller than 1.4 x head_radius.")
    if not 0 <= p.grip_grooves <= 12:
        raise ModelingError("wrench.grooves", "grip_grooves must be 0...12.")


def outline(p: WrenchParameters):
    """Full outline on the ground plane (u along +X, v across the width), built from a symmetric half."""
    hr = p.head_radius
    jaw = p.jaw_width / 2
    shaft = hr * 0.42
    head_x = p.length / 2 - hr
    jaw_angle = math.asin(jaw / hr)
    half = curves.join(
        ((0.0, -shaft),),
        ((head_x - hr * 0.6, -shaft),),
        curves.arc((head_x, 0.0), hr, -math.radians(110), -jaw_angle, 10),
        ((head_x + hr * 0.15, -jaw), (head_x + hr * 0.15, jaw)),
        curves.arc((head_x, 0.0), hr, jaw_angle, math.radians(110), 10),
        ((head_x - hr * 0.6, shaft),),
        ((0.0, shaft),),
    )
    return curves.symmetric(half, axis="u")


def build(input: GenerationInput) -> Asset:
    p: WrenchParameters = input.parameters
    steel = Material("steel", base_color=srgb(0.62, 0.63, 0.65), roughness=0.35, metallic=1.0)
    head_x = p.length / 2 - p.head_radius
    hex_hole = curves.regular_polygon(6, p.head_radius * 0.26, center=(head_x * 0.45, 0.0))
    profile = Profile(outline(p), holes=(hex_hole,))
    # Bevel the outline edges first; grooves cut afterwards keep crisp edges.
    modifiers = [Bevel(width=p.thickness * 0.18, segments=2, angle_limit=math.radians(40))]
    if p.grip_grooves:
        groove = Cutter(
            shape=Cylinder(radius=p.thickness * 0.35, height=p.head_radius * 2, segments=24),
            # Lay the cylinder across the shaft on the top surface, spun by half a
            # segment so no cutter vertex lies exactly in the top face plane.
            transform=Transform(
                translation=(-p.length * 0.12, p.thickness, 0.0),
                rotation=(math.pi / 2, 0.0, math.pi / 24),
            ),
            modifiers=(Array(count=p.grip_grooves, offset=(p.length * 0.05, 0.0, 0.0)),),
        )
        modifiers.append(Boolean("difference", cutter=groove))
    body = Part(
        id="body",
        shape=Extrude(profile=profile, depth=p.thickness, axis="y"),
        material="steel",
        modifiers=tuple(modifiers),
        smooth_angle=math.radians(50),
    )
    return Asset(name="Wrench", materials=(steel,), parts=(body,))


asset = AssetGenerator(name="Wrench", parameters=WrenchParameters(), build=build, validate=validate, seed=1)
render = RenderSettings(resolution=512, views=("perspective", "top"))
