"""Karate belt (27-karate-master, 28-karate-student). A wardrobe garment realized as a promodeler prop: the catalog
entry ``karate_belt_01`` points here (``runtime.promodeler_asset``) and the character creator centres the built GLB
on the ``waist`` socket, around the gi jacket. ``size`` is the ring's outer width (X), the band height (Y) and the
ring's outer depth (Z); the catalog maps it from the body's waist section plus the jacket ease, and the band
thickness and the ends hanging from the knot are fixed. ``color`` comes from the recipe's garment material.

Run:  python -m promodeler build assets/props/obi_belt.py
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from promodeler.core import (
    Asset, AssetGenerator, Bevel, Box, GenerationInput, Material, ModelingError, Part, RenderSettings, Revolve, Transform, curves,
)
from promodeler import props


@dataclass(frozen=True)
class Parameters:
    size: tuple[float, float, float] = (0.30, 0.045, 0.26)   # ring outer width, band height, ring outer depth
    color: str = "#E5E2D8"
    thickness: float = 0.008   # two turns of a 4 mm belt read as one 8 mm band
    end_length: float = 0.25   # the two ends hanging from the knot


def validate(p: Parameters) -> None:
    if len(p.size) != 3 or any(not 0.001 <= v <= 1.0 for v in p.size):
        raise ModelingError("obi_belt.size", "size must be three values within 1 mm...1 m.")
    if not 0.002 <= p.thickness <= 0.03:
        raise ModelingError("obi_belt.thickness", "thickness must be within 2 mm...3 cm.")
    if not 0.0 <= p.end_length <= 0.6:
        raise ModelingError("obi_belt.end_length", "end_length must be within 0...0.6 m.")
    if not (len(p.color) == 7 and p.color.startswith("#")):
        raise ModelingError("obi_belt.color", "color must be #RRGGBB.")


def build(input: GenerationInput) -> Asset:
    p: Parameters = input.parameters
    outer_w, band_h, outer_d = p.size
    t = p.thickness

    cotton = Material("cotton", base_color=props.hex_color(p.color), roughness=0.8)

    # The ring: a rectangular section revolved about Y at the outer half width, then scaled in Z to the waist's
    # depth. The profile closes on its first point so the torus is seamless (a closed Sweep overlaps at its caps).
    ring_bottom = p.end_length   # the ends hang below the ring; the asset origin stays at its lowest point
    radius = outer_w / 2 - t / 2
    section = tuple((radius + u, v) for u, v in curves.rect(t, band_h)) + ((radius - t / 2, -band_h / 2),)
    ring = Part(id="ring", shape=Revolve(profile=section, segments=48, cap_ends=False), material="cotton",
                transform=Transform(translation=(0.0, ring_bottom + band_h / 2, 0.0), scale=(1.0, 1.0, outer_d / outer_w)),
                smooth_angle=math.radians(60))
    # The flat knot in front of the ring.
    knot_w, knot_h, knot_d = band_h * 1.5, band_h * 1.1, t * 2.5
    knot_z = outer_d / 2 + knot_d / 2 - t / 2
    knot = Part(id="knot", shape=Box(size=(knot_w, knot_h, knot_d)), material="cotton",
                transform=Transform(translation=(0.0, ring_bottom + band_h / 2, knot_z)),
                modifiers=(Bevel(width=0.004, segments=3),), smooth_angle=math.radians(60))
    parts = [ring, knot]
    # Two ends hanging from the knot, splayed a little left and right.
    if p.end_length > 0.0:
        for side, sign in (("l", -1.0), ("r", 1.0)):
            angle = sign * math.radians(10.0)
            end = Part(id=f"end_{side}", shape=Box(size=(band_h, p.end_length, t / 2)), material="cotton",
                       transform=Transform(translation=(sign * knot_w * 0.3 + math.sin(angle) * p.end_length / 2,
                                                        ring_bottom - math.cos(angle) * p.end_length / 2,
                                                        outer_d / 2 - t / 2),
                                           rotation=(0.0, 0.0, angle)),
                       smooth_angle=math.radians(60))   # no bevel: a 4 mm sheet's bevel collapses into degenerate faces
            parts.append(end)
    grip = (0.0, ring_bottom + band_h / 2, 0.0)   # ring centre on the waist plane
    return Asset(name="Karate belt", materials=(cotton,), parts=tuple(parts),
                 extras=props.socket_extras("waist", grip, "follow_bone", "ring centred on the waist plane, knot in front"))


asset = AssetGenerator(name="Karate belt", parameters=Parameters(), build=build, validate=validate, seed=1)
render = RenderSettings(resolution=512, views=("perspective",))
