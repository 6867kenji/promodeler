"""Glasses (35-passerby-g). Character accessory: real dimensions, constant materials, socket extras.

The recipe's accessories[].size_xyz_m overrides ``size`` at build time (promodeler.character.bridge).
Run:  python -m promodeler build assets/props/glasses.py
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
    size: tuple[float, float, float] = (0.14, 0.04, 0.145)


def validate(p: Parameters) -> None:
    if len(p.size) != 3 or any(not 0.001 <= v <= 1.0 for v in p.size):
        raise ModelingError("glasses.size", "size must be three values within 1 mm...1 m.")


def build(input: GenerationInput) -> Asset:
    p: Parameters = input.parameters
    w, h, d = p.size

    frame = props.plastic("frame", color="#141414")
    lens = props.plastic("lens", color="#6F7E8C")
    lens_w, lens_h = w * 0.42, h * 0.9
    rim_r = 0.0015
    rims, lenses = [], []
    for i, x in enumerate((-w * 0.27, w * 0.27)):
        # A closed Revolve profile makes a seamless torus (a closed Sweep would overlap at its caps); the torus is revolved
        # about Y, then tipped to lie in the XY plane and squashed into the lens ellipse.
        tube = tuple((lens_w / 2 + u, v) for u, v in curves.circle(rim_r, 10)) + ((lens_w / 2 + rim_r, 0.0),)
        rims.append(Part(id=f"rim_{i}", shape=Revolve(profile=tube, segments=32, cap_ends=False), material="frame",
                         transform=Transform(translation=(x, h / 2, 0.0), rotation=(math.pi / 2, 0.0, 0.0), scale=(1.0, 1.0, lens_h / lens_w)),
                         smooth_angle=math.radians(70)))
        lenses.append(Part(id=f"lens_{i}", shape=Cylinder(radius=lens_w / 2, height=0.002, segments=32), material="lens",
                           transform=Transform(translation=(x, h / 2, 0.0), rotation=(math.pi / 2, 0.0, 0.0), scale=(1.0, 1.0, lens_h / lens_w)),
                           smooth_angle=math.radians(60)))
    bridge = props.cord("bridge", ((-w * 0.06, h * 0.6, 0.0), (0.0, h * 0.7, 0.0), (w * 0.06, h * 0.6, 0.0)), "frame", radius=rim_r)
    temples = tuple(props.cord(f"temple_{i}", ((x, h * 0.7, 0.0), (x * 1.02, h * 0.7, -d * 0.85), (x * 0.95, h * 0.35, -d)), "frame", radius=rim_r)
                    for i, x in enumerate((-w / 2, w / 2)))
    return Asset(name="Glasses", materials=(frame, lens), parts=(*rims, *lenses, bridge, *temples),
                 extras=props.socket_extras("face", (0.0, h / 2, 0.0), "follow_bone", "bridge sits on the nose; +Z is the wearer's front"))


asset = AssetGenerator(name="Glasses", parameters=Parameters(), build=build, validate=validate, seed=1)
render = RenderSettings(resolution=512, views=("perspective",))
