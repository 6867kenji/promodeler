"""Necktie (22-businessman). A wardrobe garment realized as a promodeler prop: the catalog entry ``necktie_01`` points
here (``runtime.promodeler_asset``) and the character creator hangs the built GLB from the ``neck`` socket, in front
of the shirt collar. The recipe's garment measurements set ``size`` (blade width, visible length, thickness) and its
material color sets ``color`` through the catalog's ``runtime.parameters`` mapping (promodeler.character.bridge).

Run:  python -m promodeler build assets/props/necktie.py
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from promodeler.core import (
    Asset, AssetGenerator, Bevel, Box, Extrude, GenerationInput, Material, ModelingError, Part, Profile, RenderSettings, Transform,
)
from promodeler import props


@dataclass(frozen=True)
class Parameters:
    size: tuple[float, float, float] = (0.075, 0.47, 0.002)   # blade width, visible length (knot top to tip), thickness
    color: str = "#244839"


def validate(p: Parameters) -> None:
    if len(p.size) != 3 or any(not 0.001 <= v <= 1.0 for v in p.size):
        raise ModelingError("necktie.size", "size must be three values within 1 mm...1 m.")
    if p.size[1] < 0.12:
        raise ModelingError("necktie.size", "the visible length must leave room for the knot (at least 0.12 m).")
    if not (len(p.color) == 7 and p.color.startswith("#")):
        raise ModelingError("necktie.color", "color must be #RRGGBB.")


def build(input: GenerationInput) -> Asset:
    p: Parameters = input.parameters
    blade_width, length, thickness = p.size
    thickness = max(thickness, 0.002)   # a 1 mm sheet shimmers at render size

    silk = Material("silk", base_color=props.hex_color(p.color), roughness=0.45)

    knot_w, knot_h, knot_d = 0.9 * blade_width * 0.55, 0.032, 0.02
    blade_len = length - knot_h
    neck_w = 0.03   # where the blade leaves the knot
    widest_y = 0.16 * blade_len   # widest point sits low on the blade, above the tip
    # Blade outline in the XY plane (tip at the origin, +Y up), extruded along +Z by the thickness (the front face
    # faces the viewer at +Z).
    outline = (
        (0.0, 0.0),
        (blade_width / 2, widest_y),
        (neck_w / 2, blade_len),
        (-neck_w / 2, blade_len),
        (-blade_width / 2, widest_y),
    )
    blade = Part(id="blade", shape=Extrude(profile=Profile(outline), depth=thickness, axis="z"), material="silk",
                 transform=Transform(translation=(0.0, 0.0, 0.0)), smooth_angle=math.radians(40))
    # The knot: a rounded wedge above the blade, thicker than the blade and slightly wider than its neck.
    knot = Part(id="knot", shape=Box(size=(knot_w, knot_h, knot_d)), material="silk",
                transform=Transform(translation=(0.0, blade_len + knot_h / 2, knot_d / 2 - thickness / 2)),
                modifiers=(Bevel(width=0.005, segments=3),), smooth_angle=math.radians(60))
    # Dimple under the knot: a small block that reads as the fold.
    dimple = Part(id="dimple", shape=Box(size=(neck_w * 0.6, 0.012, 0.006)), material="silk",
                  transform=Transform(translation=(0.0, blade_len - 0.006, thickness + 0.003)),
                  modifiers=(Bevel(width=0.002, segments=2),), smooth_angle=math.radians(60))
    grip = (0.0, length, 0.0)   # top of the knot at the neck front; the tie hangs straight down from it
    return Asset(name="Necktie", materials=(silk,), parts=(blade, knot, dimple),
                 extras=props.socket_extras("neck", grip, "follow_bone", "knot top at the collar front, blade hanging in front of the shirt"))


asset = AssetGenerator(name="Necktie", parameters=Parameters(), build=build, validate=validate, seed=1)
render = RenderSettings(resolution=512, views=("perspective",))
