"""White shirt cut on a UMA race profile (the one-garment spike of docs/03 18.8).

The garment is authored on the race's neutral body (``character/profiles/<race>.json`` from
``promodeler character profile``): the torso is a loft through the body's outlines from the hem to the collar, pushed
out by the ease, and each sleeve is a loft through the arm cross-sections along the arm in the rest pose. The result
goes through ``promodeler character import-slot`` (weight transfer to the UMA skeleton, slot + overlay + wardrobe
recipe) and is worn as the recipe's ``inner`` (UMA TopUnderlayer) garment.

The frame is the Unity body frame (metres, Y up, feet near y = 0, the character facing +Z, left arm toward -X); the
asset is symmetric, so the X mirror of the glTF import does not matter.

Run:  python -m promodeler build assets/wardrobe/white_shirt.py
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path

from promodeler.core import Asset, AssetGenerator, GenerationInput, Loft, LoftSection, Material, ModelingError, Part, RenderSettings, Transform
from promodeler import props

ROOT = Path(__file__).resolve().parents[2]


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
    if not (ROOT / p.profile).is_file():
        raise ModelingError("white_shirt.profile", f"race profile not found: {ROOT / p.profile} (run `promodeler character profile <race>`).")
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


def _resample(points, ease: float, count: int) -> list[tuple[float, float]]:
    """A convex outline (a, b) pushed outward by ``ease`` and resampled at ``count`` uniform polar angles from its
    centroid, starting at +b (the front for torso slices), so every section of a loft shares its point order."""
    cx = sum(a for a, _ in points) / len(points)
    cy = sum(b for _, b in points) / len(points)
    polar = sorted(((math.atan2(a - cx, b - cy), math.hypot(a - cx, b - cy) + ease) for a, b in points))
    if not polar:
        raise ModelingError("white_shirt.profile", "empty outline in the race profile.")
    angles = [t for t, _ in polar] + [polar[0][0] + 2 * math.pi]
    radii = [r for _, r in polar] + [polar[0][1]]
    out = []
    for i in range(count):
        theta = -math.pi + 2 * math.pi * i / count
        # locate the segment containing theta (angles are sorted in [-pi, pi], wrapped once)
        t = theta if theta >= angles[0] else theta + 2 * math.pi
        j = 0
        while j + 1 < len(angles) and angles[j + 1] < t:
            j += 1
        a0, a1 = angles[j], angles[min(j + 1, len(angles) - 1)]
        r0, r1 = radii[j], radii[min(j + 1, len(radii) - 1)]
        f = 0.0 if a1 <= a0 else (t - a0) / (a1 - a0)
        r = r0 + (r1 - r0) * max(0.0, min(1.0, f))
        out.append((cx + r * math.sin(theta), cy + r * math.cos(theta)))
    return out


def _torso(profile: dict, p: Parameters) -> Part:
    hem_y = profile["floor"] + p.hem_fraction * profile["height"]
    top_y = profile["neck_y"] - p.collar_drop_m
    sections = []
    for slice_ in profile["torso_slices"]:
        y = slice_["y"]
        if y < hem_y - 0.02 or y > top_y:
            continue
        ring = _resample(slice_["points"], p.ease_m, p.torso_points)
        # LoftSection points lie on the local XZ plane facing +Y: (u, v) -> (u, 0, -v), so u = x and v = -z.
        sections.append(LoftSection(points=tuple((x, -z) for x, z in ring), transform=Transform(translation=(0.0, y, 0.0))))
    if len(sections) < 3:
        raise ModelingError("white_shirt.profile", "the race profile has too few torso slices between the hem and the collar.")
    return Part(id="torso", shape=Loft(sections=tuple(sections), capped=False), material="cotton", smooth_angle=math.radians(60))


def _sleeve(side: str, arm: dict, p: Parameters) -> Part | None:
    """A loft through the arm's cross-sections along the shoulder-to-wrist axis. The profile gives each section as
    (a, b) in the plane perpendicular to the axis, a along e1 = (cos angle_z, sin angle_z, 0) and b along +Z; a
    LoftSection rotated by angle_z about Z maps its local (u, 0, -v) onto that plane as (a, b) = (u, -v)."""
    slices = arm.get("slices") or []
    if len(slices) < 2 or "angle_z" not in arm:
        return None
    angle = float(arm["angle_z"])
    dir_ = arm["dir"]
    reach = float(arm["length"]) * p.sleeve_length
    sections = []
    for slice_ in slices:
        if float(slice_["t"]) > reach:
            break
        ring = _resample(slice_["points"], p.sleeve_ease_m, p.sleeve_points)
        sections.append(LoftSection(points=tuple((a, -b) for a, b in ring),
                                    transform=Transform(translation=tuple(float(c) for c in slice_["center"]), rotation=(0.0, 0.0, angle))))
    if len(sections) < 2:
        return None
    # Bury the sleeve root inside the torso: repeat the first section 4 cm back along the axis toward the body.
    first = sections[0]
    t = first.transform.translation
    root = LoftSection(points=first.points, transform=Transform(translation=(t[0] - 0.04 * dir_[0], t[1] - 0.04 * dir_[1], t[2]), rotation=(0.0, 0.0, angle)))
    return Part(id=f"sleeve_{side}", shape=Loft(sections=(root, *sections), capped=False), material="cotton", smooth_angle=math.radians(60))


def build(input: GenerationInput) -> Asset:
    p: Parameters = input.parameters
    profile = json.loads((ROOT / p.profile).read_text(encoding="utf-8"))
    cotton = Material("cotton", base_color=props.hex_color(p.color), roughness=0.75)
    parts = [_torso(profile, p)]
    for side in ("left", "right"):
        arm = profile.get("arms", {}).get(side)
        sleeve = _sleeve(side, arm, p) if arm else None
        if sleeve is not None:
            parts.append(sleeve)
    return Asset(name="White shirt", materials=(cotton,), parts=tuple(parts),
                 extras={"promodeler_garment": {"race": profile.get("race"), "uma_race": profile.get("uma_race"), "profile": p.profile,
                                                "wardrobe_slot": "TopUnderlayer", "frame": "unity body frame (metres, Y up, faces +Z)"}})


asset = AssetGenerator(name="White shirt", parameters=Parameters(), build=build, validate=validate, seed=1)
render = RenderSettings(resolution=512, views=("perspective", "front"))
