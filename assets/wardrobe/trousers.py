"""Trousers cut on a UMA race profile (docs/03 18.14): a waist-to-hip torso loft and one leg tube per leg.

The waistband sits at ``waist_fraction`` of the body height, the seat follows the torso outlines down to the hip
joints, and each leg is a loft through the profile's leg cross-sections with ``leg_ease_m`` of room, ending at
``leg_length`` of the hip-to-ankle axis (0.94 = above the shoe, 0.55 = shorts). Worn as the recipe's ``lower``
garment (UMA Legs) after ``promodeler character import-slot``; other races get it through ``fit-garment``.

Run:  python -m promodeler build assets/wardrobe/trousers.py
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from promodeler import garments
from promodeler import props
from promodeler.core import Asset, AssetGenerator, GenerationInput, Loft, Material, ModelingError, Part, RenderSettings


@dataclass(frozen=True)
class Parameters:
    profile: str = "character/profiles/human_female.json"
    color: str = "#2E3A5A"
    waist_fraction: float = 0.585    # waistband height as a fraction of the body height (natural waist is ~0.66; trousers sit lower)
    seat_ease_m: float = 0.02        # ease over the hip/seat outline
    leg_ease_m: float = 0.03         # ease over the leg sections (0.02 slim, 0.045 wide)
    leg_length: float = 0.94         # fraction of the hip-to-ankle axis covered
    torso_points: int = 40
    leg_points: int = 24


def validate(p: Parameters) -> None:
    garments.load_profile(p.profile)
    if not 0.5 <= p.waist_fraction <= 0.7:
        raise ModelingError("trousers.waist", "waist_fraction must be within 0.5...0.7 of the body height.")
    if not 0.0 <= p.seat_ease_m <= 0.1 or not 0.0 <= p.leg_ease_m <= 0.12:
        raise ModelingError("trousers.ease", "ease must be within 0...10 cm (seat) and 0...12 cm (legs).")
    if not 0.3 <= p.leg_length <= 1.0:
        raise ModelingError("trousers.leg", "leg_length must be within 0.3...1.0.")
    if p.torso_points < 12 or p.leg_points < 8:
        raise ModelingError("trousers.points", "torso_points >= 12 and leg_points >= 8.")
    if not (len(p.color) == 7 and p.color.startswith("#")):
        raise ModelingError("trousers.color", "color must be #RRGGBB.")


def build(input: GenerationInput) -> Asset:
    p: Parameters = input.parameters
    profile = garments.load_profile(p.profile)
    twill = Material("twill", base_color=props.hex_color(p.color), roughness=0.7)
    legs = profile.get("legs") or {}
    hip_joint_y = min((float(leg["hip"][1]) for leg in legs.values()), default=profile["bones"]["Hips"][1] - 0.02)
    waist_y = profile["floor"] + p.waist_fraction * profile["height"]
    seat = garments.torso_sections(profile, hip_joint_y - 0.02, waist_y, p.seat_ease_m, p.torso_points, margin=0.01)
    if len(seat) < 2:
        raise ModelingError("trousers.profile", "the race profile has too few torso slices between the hip joints and the waist.")
    parts = [Part(id="seat", shape=Loft(sections=tuple(seat), capped=False), material="twill", smooth_angle=math.radians(60))]
    for side, leg in legs.items():
        if len(leg.get("slices") or []) < 2:
            continue
        reach = float(leg["length"]) * p.leg_length
        sections = garments.limb_sections(leg, 0.0, reach, p.leg_ease_m, p.leg_points, root_extension=0.06)
        parts.append(Part(id=f"leg_{side}", shape=Loft(sections=tuple(sections), capped=False), material="twill", smooth_angle=math.radians(60)))
    if len(parts) < 3:
        raise ModelingError("trousers.profile", "the race profile has no leg sections (re-export it with `promodeler character profile`).")
    return Asset(name="Trousers", materials=(twill,), parts=tuple(parts),
                 extras=garments.garment_extras(profile, p.profile, "Legs", leg_length=p.leg_length))


asset = AssetGenerator(name="Trousers", parameters=Parameters(), build=build, validate=validate, seed=1)
render = RenderSettings(resolution=512, views=("perspective", "front"))
