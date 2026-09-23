"""White shirt cut on a UMA race profile (the one-garment spike of docs/03 18.8).

The garment is authored on the race's neutral body (``character/profiles/<race>.json`` from
``promodeler character profile``): the torso is a loft through the body's outlines from the hem to the collar, pushed
out by the ease, and each sleeve is a loft through the arm cross-sections along the arm in the generated pose. The
result goes through ``promodeler character import-slot`` (weight transfer to the UMA skeleton, slot + overlay +
wardrobe recipe) and is worn as the recipe's ``inner`` (UMA TopUnderlayer) garment; ``sleeve_length`` 0.3 makes it
a T-shirt, 0.75 a three-quarter sleeve, 1.0 a long sleeve.

Run:  python -m promodeler build assets/wardrobe/white_shirt.py
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from promodeler import garments
from promodeler import props
from promodeler.core import Asset, AssetGenerator, GenerationInput, Loft, Material, ModelingError, Part, RenderSettings


@dataclass(frozen=True)
class Parameters:
    profile: str = "character/profiles/human_female.json"   # race profile, relative to the repository
    color: str = "#F4F2EC"
    ease_m: float = 0.025            # torso ease over the body outline
    sleeve_ease_m: float = 0.018     # sleeve ease over the arm section
    hem_fraction: float = 0.50       # hem height as a fraction of the body height (0.50 = hip)
    collar_drop_m: float = 0.015     # collar line below the Neck bone
    sleeve_length: float = 0.75      # fraction of shoulder-to-wrist covered (0.75 = three-quarter sleeve)
    torso_points: int = 48
    sleeve_points: int = 24


def validate(p: Parameters) -> None:
    garments.load_profile(p.profile)
    if not 0.0 <= p.ease_m <= 0.15 or not 0.0 <= p.sleeve_ease_m <= 0.1:
        raise ModelingError("white_shirt.ease", "ease must be within 0...15 cm (torso) and 0...10 cm (sleeve).")
    if not 0.35 <= p.hem_fraction <= 0.7:
        raise ModelingError("white_shirt.hem", "hem_fraction must be within 0.35...0.7 of the body height.")
    if not 0.1 <= p.sleeve_length <= 1.0:
        raise ModelingError("white_shirt.sleeve", "sleeve_length must be within 0.1...1.0.")
    if p.torso_points < 12 or p.sleeve_points < 8:
        raise ModelingError("white_shirt.points", "torso_points >= 12 and sleeve_points >= 8.")
    if not (len(p.color) == 7 and p.color.startswith("#")):
        raise ModelingError("white_shirt.color", "color must be #RRGGBB.")


def build(input: GenerationInput) -> Asset:
    p: Parameters = input.parameters
    profile = garments.load_profile(p.profile)
    cotton = Material("cotton", base_color=props.hex_color(p.color), roughness=0.75)
    hem_y = profile["floor"] + p.hem_fraction * profile["height"]
    top_y = profile["neck_y"] - p.collar_drop_m
    torso = garments.torso_sections(profile, hem_y, top_y, p.ease_m, p.torso_points, margin=0.02)
    if len(torso) < 3:
        raise ModelingError("white_shirt.profile", "the race profile has too few torso slices between the hem and the collar.")
    parts = [Part(id="torso", shape=Loft(sections=tuple(torso), capped=False), material="cotton", smooth_angle=math.radians(60))]
    for side in ("left", "right"):
        arm = profile.get("arms", {}).get(side)
        if not arm or len(arm.get("slices") or []) < 2:
            continue
        reach = float(arm["length"]) * p.sleeve_length
        try:
            sections = garments.limb_sections(arm, 0.0, reach, p.sleeve_ease_m, p.sleeve_points, root_extension=0.04)
        except ModelingError:
            continue
        parts.append(Part(id=f"sleeve_{side}", shape=Loft(sections=tuple(sections), capped=False), material="cotton", smooth_angle=math.radians(60)))
    return Asset(name="White shirt", materials=(cotton,), parts=tuple(parts),
                 extras=garments.garment_extras(profile, p.profile, "TopUnderlayer", sleeve_length=p.sleeve_length))


asset = AssetGenerator(name="White shirt", parameters=Parameters(), build=build, validate=validate, seed=1)
render = RenderSettings(resolution=512, views=("perspective", "front"))
