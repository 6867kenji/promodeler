"""Haruka (blueprints/japan-realistic-v1/05-woman), body v2: Meta MHR body fitted to the blueprint.

The body comes from ``promodeler.human.mhr``: Meta's Momentum Human Rig
(skeletal scales + identity coefficients) fitted to the blueprint's
height, inseam, shoulder width, foot and head sizes and the
bust/underbust/waist/hip circumferences, exported as the LOD1 mesh with
UVs, skin weights and the 126-joint skeleton. This file loads that export
through ``MeshFile`` and ``rig_from_file`` and adds what MHR does not
provide: skin, hair, cloth, rubber materials; a cloth-draped U-neck dress
with the blueprint's 12 chest gathers fitted to the measured torso; hair
as a scalp cap plus bundle strands (bangs, face-framing, back) falling to
the blueprint's 0.66 m; white sneakers with laces on each foot (the body
stands on the 25 mm soles, so the shod height is 1.625 m); and the
blueprint's poses and clips in MHR joint names.

Eyes: the MHR LOD1 body is a closed shell with lids but no sockets, so two
ellipsoid booleans open the sockets at the MHR eye joints and eyeball
parts (24 mm, 11.5 mm iris, attached to the eye joints for gaze) sit in
them. Teeth stay open (the mouth is closed). Head identity coefficients
are fitted to the blueprint's head/neck width and depth; the blueprint
gives no other face numbers. Runtime physics cannot live in a GLB: the
blueprint's physics block is delivered as ``extras.json`` and glTF extras.

Run:  python -m promodeler build assets/haruka.py --texture-resolution 512 --bake-samples 8
Pose check:  --pose raise_arms --views front,side   (also step_r, sit, range_check, turn_180)
First build fits the body (about 40 s, torch on CPU); later builds reuse build/human/haruka-*.
"""

from __future__ import annotations

import json
import math
import random
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from promodeler.core import (
    Asset, AssetGenerator, Bevel, Boolean, Camera, Clip, ClothDrape, Cutter, Extrude, GenerationInput, JointTransform,
    Keyframe, Layer, Loft, LoftSection, Material, MeshFile, ModelingError, Noise, Part, Pose, Position, Profile,
    QualityProfile, RenderSettings, Solidify, Sphere, Strands, Subdivision, Sweep, Transform, curves, srgb,
)
from promodeler.human.mhr import blueprint_targets, fitted_body, rig_from_file

ROOT = Path(__file__).resolve().parent.parent
BLUEPRINT = ROOT / "blueprints" / "japan-realistic-v1" / "05-woman" / "blueprint.json"


@dataclass(frozen=True)
class HarukaParameters:
    shoes: bool = True
    shoe_sole: float = 0.025
    dress_hem_height: float = 0.48
    dress_ease: float = 0.03  # extra width/depth over the measured torso, meters
    gathers: int = 12
    hair_length: float = 0.66
    hair_thickness: float = 0.012
    hair_bundles: int = 96
    cloth_frames: int = 60


def validate(p: HarukaParameters) -> None:
    if not 0.01 <= p.shoe_sole <= 0.06:
        raise ModelingError("haruka.sole", "shoe_sole must be 1...6 cm.")
    if not 0.3 <= p.dress_hem_height <= 0.9:
        raise ModelingError("haruka.hem", "dress_hem_height must be 0.3...0.9 m.")
    if not 0.0 <= p.dress_ease <= 0.15:
        raise ModelingError("haruka.ease", "dress_ease must be 0...0.15 m.")
    if not 0 <= p.gathers <= 40:
        raise ModelingError("haruka.gathers", "gathers must be 0...40.")
    if not 0.1 <= p.hair_length <= 1.0:
        raise ModelingError("haruka.hair", "hair_length must be 0.1...1 m.")
    if not 0.004 <= p.hair_thickness <= 0.05:
        raise ModelingError("haruka.hairThickness", "hair_thickness must be 4...50 mm.")
    if not 8 <= p.hair_bundles <= 400:
        raise ModelingError("haruka.hairBundles", "hair_bundles must be 8...400.")
    if not 10 <= p.cloth_frames <= 240:
        raise ModelingError("haruka.cloth", "cloth_frames must be 10...240.")


SEGMENTS = 40
DRESS_SEGMENTS = 128  # 7 mm spacing, 3.5 mm after smooth subdivision; keeps the dress under 22k triangles


def ellipse(width: float, depth: float, points: int = SEGMENTS):
    return tuple((u * width / 2, v * depth / 2) for u, v in curves.circle(1.0, points))


class BodyMeasure:
    """Horizontal slices of the fitted body (barefoot coordinates), used to fit clothing, hair and shoes."""

    def __init__(self, mesh_path: str) -> None:
        self.vertices = np.load(mesh_path)["vertices"].astype(float)
        self.height = float(self.vertices[:, 1].max())

    def select(self, y: float, x_limit: float = 0.2, band: float = 0.012, side: int = 0) -> np.ndarray:
        v = self.vertices
        mask = (np.abs(v[:, 1] - y) < band) & (np.abs(v[:, 0]) < x_limit)
        if side:
            mask &= np.sign(v[:, 0]) == side
        s = v[mask]
        if len(s) < 8:
            raise ModelingError("haruka.slice", f"No body surface at height {y:.3f} m.")
        return s

    def slice(self, y: float, x_limit: float = 0.2, band: float = 0.012) -> tuple[float, float, float]:
        """(width, depth, z center) of the torso/head slice at height ``y``."""
        s = self.select(y, x_limit, band)
        width = float(s[:, 0].max() - s[:, 0].min())
        depth = float(s[:, 2].max() - s[:, 2].min())
        return width, depth, float((s[:, 2].max() + s[:, 2].min()) / 2)

    def front_back(self, y: float, x_limit: float = 0.2) -> tuple[float, float]:
        s = self.select(y, x_limit)
        return float(s[:, 2].max()), float(s[:, 2].min())

    def foot(self, side: int) -> dict:
        """Extents of one foot below the ankle: x/z ranges of the sole print and of the ankle."""
        v = self.vertices
        f = v[(v[:, 1] < 0.09) & (np.sign(v[:, 0]) == side)]
        ankle = v[(np.abs(v[:, 1] - 0.08) < 0.006) & (np.sign(v[:, 0]) == side)]
        return {
            "x": (float(f[:, 0].min()), float(f[:, 0].max())), "z": (float(f[:, 2].min()), float(f[:, 2].max())),
            "ankle_x": (float(ankle[:, 0].min()), float(ankle[:, 0].max())),
            "ankle_z": (float(ankle[:, 2].min()), float(ankle[:, 2].max())),
        }


def build(input: GenerationInput) -> Asset:
    p: HarukaParameters = input.parameters
    seed = input.seed
    rng = random.Random(seed)

    blueprint = json.loads(BLUEPRINT.read_text(encoding="utf-8"))
    fit = fitted_body(blueprint_targets(blueprint), out_root=ROOT / "build" / "human", name="haruka")
    measure = BodyMeasure(fit["mesh"])
    height = measure.height
    lift = p.shoe_sole if p.shoes else 0.0  # the barefoot body stands on the soles

    def section(width: float, depth: float, y: float, z: float = 0.0, points: int = SEGMENTS,
                rotation: tuple[float, float, float] = (0.0, 0.0, 0.0), ring=None) -> LoftSection:
        """Ring at barefoot height ``y`` (lifted by the soles); ``rotation`` tilts the ring plane."""
        return LoftSection(ring or ellipse(width, depth, points), Transform(translation=(0.0, y + lift, z), rotation=rotation))

    def fitted(y: float, ease: float, x_limit: float = 0.2, points: int = SEGMENTS) -> LoftSection:
        width, depth, zc = measure.slice(y, x_limit)
        return section(width + ease, depth + ease, y, zc, points)

    # --- materials (blueprint materials block) ---------------------------------------------
    def box(axis: str, a: float, b: float, soft: float):
        """1 inside a...b along the object axis, fading to 0 over ``soft`` outside it."""
        return Position(axis, a - soft, a) * Position(axis, b + soft, b)

    cheeks = (box("x", 0.035, 0.075, 0.015) + box("x", -0.075, -0.035, 0.015)) * box("y", 1.455, 1.50, 0.015) * Position("z", 0.06, 0.10)
    under_eye = (box("x", 0.018, 0.05, 0.01) + box("x", -0.05, -0.018, 0.01)) * box("y", 1.478, 1.494, 0.006) * Position("z", 0.08, 0.10)
    lips = box("x", -0.022, 0.022, 0.006) * box("y", 1.409, 1.427, 0.004) * Position("z", 0.115, 0.13)
    nose = box("x", -0.02, 0.02, 0.01) * box("y", 1.45, 1.49, 0.01) * Position("z", 0.12, 0.14)
    skin = Material(
        "skin", base_color=srgb(0.922, 0.824, 0.765), roughness=0.42 + Noise(size=0.02, detail=3.0, seed=seed) * 0.13,
        height=Noise(size=0.0003, detail=2.0, roughness=0.6, seed=seed + 1) * 0.00003,
        layers=(
            Layer(base_color=srgb(0.86, 0.68, 0.64), mask=(Noise(size=0.08, detail=2.0, seed=seed + 2) * 0.35).clamp()),
            Layer(base_color=srgb(0.90, 0.62, 0.60), mask=(cheeks * 0.45).clamp()),
            Layer(base_color=srgb(0.84, 0.70, 0.69), mask=(under_eye * 0.35).clamp()),
            Layer(base_color=srgb(0.80, 0.45, 0.45), roughness=0.36, mask=(lips * 0.85).clamp()),
            Layer(roughness=0.30, mask=(nose * 0.8).clamp()),
        ),
        bump_strength=1.0,
    )
    hair = Material(
        "hair", base_color=srgb(0.188, 0.125, 0.106), roughness=0.3 + Noise(size=(0.003, 0.25, 0.003), detail=3.0, seed=seed + 3) * 0.15,
        height=Noise(size=(0.0015, 0.3, 0.0015), detail=2.0, seed=seed + 4) * 0.0002, bump_strength=1.5,
    )
    cloth = Material(
        "cloth", base_color=srgb(0.718, 0.769, 0.698), roughness=0.75 + Noise(size=0.0025, detail=4.0, seed=seed + 5) * 0.1,
        height=Noise(size=(0.0004, 0.0004, 0.0004), detail=2.0, seed=seed + 6) * 0.00004, bump_strength=1.2,
    )
    ground_wear = Position("y", 0.012, 0.002)  # 1 at the sole's ground edge, 0 above 12 mm
    rubber = Material(
        "rubber", base_color=srgb(0.898, 0.890, 0.863), roughness=0.72 + Noise(size=0.001, detail=2.0, seed=seed + 7) * 0.1,
        height=Noise(size=(0.0007, 0.02, 0.0007), detail=1.0, seed=seed + 8) * 0.0002,
        layers=(Layer(base_color=srgb(0.72, 0.71, 0.69), roughness=0.85, mask=(ground_wear * 0.6).clamp()),),
        bump_strength=1.0,
    )
    canvas = Material(
        "canvas", base_color=srgb(0.93, 0.92, 0.90), roughness=0.8 + Noise(size=0.0015, detail=3.0, seed=seed + 9) * 0.1,
        height=Noise(size=(0.0004, 0.0004, 0.0004), detail=1.0, seed=seed + 10) * 0.00003, bump_strength=1.2,
    )
    lace = Material("lace", base_color=srgb(0.95, 0.94, 0.92), roughness=0.7)

    # --- body ---------------------------------------------------------------------------
    rig = rig_from_file(fit["rig"], rig_id="haruka", offset=(0.0, lift, 0.0))
    joint_heads = {j["id"]: tuple(j["head"]) for j in json.loads(Path(fit["rig"]).read_text(encoding="utf-8"))["joints"]}
    # Eye sockets: the MHR shell has lids but no openings. An ellipsoid centred 6 mm in front of the eye
    # joint cuts an almond-shaped opening at the lid surface and leaves a cavity for the eyeball.
    socket_cutters = tuple(
        Cutter(shape=Sphere(radius=0.01, segments=24, rings=12),
               transform=Transform(translation=(ex, ey, ez + 0.006), scale=(1.4, 1.0, 1.8)))
        for ex, ey, ez in (joint_heads["l_eye"], joint_heads["r_eye"])
    )
    body = Part(
        id="body", shape=MeshFile(fit["mesh"]), material="skin", transform=Transform(translation=(0.0, lift, 0.0)),
        modifiers=tuple(Boolean("difference", cutter=c) for c in socket_cutters),
        smooth_angle=math.radians(60), skinned=True,
    )
    eye = Material(  # 24 mm eyeball, 11.5 mm brown iris, 3.5 mm pupil; masks are object-space heights along +Z
        "eye", base_color=srgb(0.93, 0.91, 0.89), roughness=0.12,
        layers=(
            Layer(base_color=srgb(0.30, 0.17, 0.10), mask=Position("z", 0.0101, 0.0108)),
            Layer(base_color=srgb(0.45, 0.27, 0.16), mask=Position("z", 0.0110, 0.0114) * Position("z", 0.0119, 0.0116)),
            Layer(base_color=srgb(0.02, 0.02, 0.02), mask=Position("z", 0.01185, 0.01195)),
        ),
    )
    eyeballs = tuple(
        Part(id=f"eye_{tag}", shape=Sphere(radius=0.012, segments=32, rings=16), material="eye",
             transform=Transform(translation=(ex, ey + lift, ez + 0.003)), parent_joint=f"{tag}_eye",
             smooth_angle=math.radians(80))
        for tag, (ex, ey, ez) in (("l", joint_heads["l_eye"]), ("r", joint_heads["r_eye"]))
    )

    # --- dress: U-neck with chest gathers, fitted tube, A-line skirt, cloth-draped ----------------
    ease = p.dress_ease
    hem_flare = 0.42

    def gathered_ring(width: float, depth: float, amount: float):
        """Ellipse whose front center (120 mm wide) carries ``gathers`` ridges of amplitude ``amount``."""
        ring = []
        for u, v in curves.circle(1.0, DRESS_SEGMENTS):
            x, zz = u * width / 2, v * depth / 2  # v < 0 is the front (+Z) in the loft plane
            if p.gathers and zz < 0 and abs(x) < 0.06:
                wave = math.cos(math.pi * p.gathers * x / 0.12) * math.cos(math.pi * x / 0.12)
                zz -= amount * (0.5 + 0.5 * wave)
            ring.append((x, zz))
        return tuple(ring)

    # Top ring tilted 28 degrees: the front dips to about 1.23 m (loose U-neck), the back rises to
    # about 1.34 m over the shoulder blades, the sides pass under the arms.
    top_w, top_d, top_z = measure.slice(1.29)
    ring_w, ring_d, ring_z = measure.slice(1.21)
    dress_sections = (
        LoftSection(gathered_ring(top_w + ease, top_d + ease, 0.004),
                    Transform(translation=(0.0, 1.285 + lift, top_z), rotation=(math.radians(28), 0.0, 0.0))),
        LoftSection(gathered_ring(ring_w + ease, ring_d + ease, 0.0025), Transform(translation=(0.0, 1.21 + lift, ring_z))),
        fitted(1.18, ease, points=DRESS_SEGMENTS),
        fitted(1.06, ease, points=DRESS_SEGMENTS),
        fitted(0.95, ease, points=DRESS_SEGMENTS),
    )
    hip_w, hip_d, hip_z = measure.slice(0.95)
    skirt_rings = 6  # rings every ~8 cm keep the cloth quads near square so the drape does not buckle
    for i in range(1, skirt_rings + 1):
        f = i / skirt_rings
        y = 0.95 + (p.dress_hem_height - 0.95) * f
        dress_sections += (section(hip_w + ease + (hem_flare - hip_w - ease) * f,
                                   hip_d + ease + (hem_flare * 0.85 - hip_d - ease) * f, y, hip_z, DRESS_SEGMENTS),)
    dress = Part(
        id="dress",
        shape=Loft(sections=dress_sections, capped=False),
        material="cloth",
        modifiers=(
            Subdivision(levels=1, smooth=True),
            ClothDrape(frames=p.cloth_frames, mass=0.14, stiffness=10.0, bending=0.05, damping=6.0, quality=6,
                       thickness=0.004, pin=Position("y", 1.17 + lift, 1.24 + lift)),
            Solidify(thickness=0.0015, offset=0.0),
        ),
        smooth_angle=math.radians(60),
        skinned=True,
    )

    # --- hair: scalp cap + bundles ------------------------------------------------------------
    t = p.hair_thickness * 2
    _, _, crown_z = measure.slice(height - 0.03, x_limit=0.12)
    brow_width, brow_depth, brow_z = measure.slice(height - 0.09, x_limit=0.12)
    hair_cap = Loft(sections=(
        section(brow_width + t, brow_depth * 0.75 + t, height - 0.10, brow_z - brow_depth * 0.14),
        fitted(height - 0.07, t, x_limit=0.12),
        fitted(height - 0.03, t, x_limit=0.12),
        section(0.05, 0.06, height + p.hair_thickness, crown_z),
    ), capped=True)
    hair_cap_part = Part(id="hair", shape=hair_cap, material="hair", smooth_angle=math.radians(50), skinned=True)

    # Skull ellipsoid from the measured head (barefoot coordinates).
    skull_w, skull_d, skull_z = measure.slice(height - 0.10, x_limit=0.12)
    skull_center = np.array([0.0, height - 0.10, skull_z])
    skull_radii = np.array([skull_w / 2 + 0.004, 0.10 + 0.004, skull_d / 2 + 0.004])
    chest_front, _ = measure.front_back(1.25)
    _, shoulder_back = measure.front_back(1.30)
    _, back_at_waist = measure.front_back(1.06)
    tip_y = height - p.hair_length

    def on_skull(azimuth: float, polar: float, offset: float = 0.0) -> np.ndarray:
        """Point on the skull ellipsoid; azimuth 0 faces +Z (the face), polar 0 is the crown."""
        direction = np.array([math.sin(polar) * math.sin(azimuth), math.cos(polar), math.sin(polar) * math.cos(azimuth)])
        return skull_center + direction * (skull_radii + offset)

    def hairline(azimuth: float) -> float:
        """Polar angle of the hairline: high on the forehead, above the ears, down to the nape."""
        blend = (1.0 - math.cos(azimuth)) / 2.0  # 0 front, 1 back
        return math.radians(55.0 + 40.0 * blend)

    def normal_at(azimuth: float, polar: float) -> tuple[float, float, float]:
        d = np.array([math.sin(polar) * math.sin(azimuth), math.cos(polar), math.sin(polar) * math.cos(azimuth)])
        n = d / skull_radii
        n = n / np.linalg.norm(n)
        return (float(n[0]), float(n[1]), float(n[2]))

    def strand(path: list[np.ndarray], width: float, thickness: float, taper: float, up=None) -> Sweep:
        pts = tuple((float(q[0]), float(q[1] + lift), float(q[2])) for q in path)
        n = len(pts)
        scales = tuple(1.0 - (1.0 - taper) * (i / (n - 1)) ** 2 for i in range(n))
        # Profile u follows ``up`` (the skull normal), so the thin axis of the bundle points off the scalp.
        return Sweep(profile=Profile(ellipse(thickness, width, 10)), path=pts, scales=scales, capped=True, up=up)

    def hanging(exit_point: np.ndarray, target_xz: tuple[float, float], end_y: float, steps: int = 6) -> list[np.ndarray]:
        """Fall from the skull exit to ``end_y`` while easing x/z toward the hang position."""
        out = []
        for i in range(1, steps + 1):
            f = i / steps
            y = exit_point[1] + (end_y - exit_point[1]) * f
            ease_f = min(1.0, f * 2.2)
            w = ease_f * ease_f * (3 - 2 * ease_f)
            x = exit_point[0] + (target_xz[0] - exit_point[0]) * w
            z = exit_point[2] + (target_xz[1] - exit_point[2]) * w
            out.append(np.array([x, y, z]))
        return out

    strands: list[Sweep] = []
    guides: list[dict] = []  # blueprint physics: 8 back + 2 per side + 2 bang guide chains of 4-6 nodes

    def guide(group: str, path: list[np.ndarray], nodes: int = 5) -> None:
        picks = [path[round(i * (len(path) - 1) / (nodes - 1))] for i in range(nodes)]
        guides.append({"id": f"{group}_{sum(g['group'] == group for g in guides)}", "group": group,
                       "nodes": [[round(float(q[0]), 4), round(float(q[1] + lift), 4), round(float(q[2]), 4)] for q in picks]})

    # Bangs: overlapping short bundles from the front hairline down over the forehead to the brow.
    for i in range(13):
        az = math.radians(-33 + 5.5 * i) + rng.uniform(-0.02, 0.02)
        offset = 0.003 + rng.uniform(0.0, 0.002)
        pol0 = hairline(az) - math.radians(10)
        path = [on_skull(az, pol0 + math.radians(9) * k, offset + 0.0015 * k) for k in range(5)]
        path[-1][1] = max(path[-1][1], height - 0.095)
        strands.append(strand(path, 0.018, 0.005, 0.45, up=normal_at(az, pol0)))
        if i in (3, 9):
            guide("bangs", path, nodes=4)
    # Face-framing bundles: two per side, falling in front of the shoulders onto the chest.
    for side in (-1, 1):
        for k in range(2):
            az = side * math.radians(46 + 12 * k) + rng.uniform(-0.03, 0.03)
            offset = 0.004 + 0.006 * k
            pol0 = hairline(az) - math.radians(12)
            path = [on_skull(az, pol0 + math.radians(12) * j, offset) for j in range(4)]
            target = (side * (0.07 + 0.02 * k), chest_front + 0.02 + 0.01 * k)
            path += hanging(path[-1], target, tip_y + 0.12 + rng.uniform(-0.03, 0.03))
            strands.append(strand(path, 0.018, 0.006, 0.35, up=normal_at(az, pol0)))
            guide("side_l" if side > 0 else "side_r", path, nodes=6)
    # Back and side bundles in three layers over the 240 degrees behind the face. Inner bundles start near
    # the crown and hug the skull; outer layers start lower, emerge from under the inner ones and add the
    # blueprint's 20-35 mm back volume. Widths are about twice the azimuth spacing so the scalp is covered.
    layers = 3
    per_layer = max(1, p.hair_bundles // layers)
    span = math.radians(240)
    for layer in range(layers):
        offset = 0.002 + 0.007 * layer
        for i in range(per_layer):
            az = math.pi + (i + 0.5 + rng.uniform(-0.15, 0.15)) / per_layer * span - span / 2
            pol0 = math.radians(18 + 16 * layer) + rng.uniform(-0.04, 0.04)
            exit_polar = math.radians(92)
            steps = 5
            path = [on_skull(az, pol0 + (exit_polar - pol0) * k / steps, offset) for k in range(steps + 1)]
            behind = abs(math.sin(az)) < 0.75  # mostly back-facing bundles hang behind the shoulders
            x_exit = float(path[-1][0])
            if behind:
                target = (x_exit * 0.75, shoulder_back - 0.02 - 0.012 * layer)
            else:
                target = (math.copysign(0.13 + 0.01 * layer, x_exit), min(shoulder_back - 0.02, back_at_waist - 0.05))
            end_y = tip_y + rng.uniform(0.0, 0.03) + 0.015 * layer  # lowest tips reach the blueprint length
            path += hanging(path[-1], target, end_y)
            width = 2.2 * (0.1 * span / per_layer) * (1.0 + 0.15 * rng.random())
            strands.append(strand(path, width, 0.005 + 0.002 * layer, 0.5, up=normal_at(az, pol0)))
            if layer == 2 and i % max(1, per_layer // 8) == per_layer // 16 and sum(g["group"] == "back" for g in guides) < 8:
                guide("back", path, nodes=6)
    hair_strands = Part(id="hair_strands", shape=Strands(strands=tuple(strands)), material="hair",
                        smooth_angle=math.radians(60), skinned=True)

    # --- sneakers ---------------------------------------------------------------------------
    shoe_parts: list[Part] = []
    if p.shoes:
        for side, tag in ((1, "l"), (-1, "r")):
            foot = measure.foot(side)
            cx = (foot["x"][0] + foot["x"][1]) / 2
            z0, z1 = foot["z"][0] - 0.008, foot["z"][1] + 0.012  # heel margin, 12 mm toe room
            length = z1 - z0
            width = foot["x"][1] - foot["x"][0] + 0.018
            cz = (z0 + z1) / 2
            sole_outline = curves.rounded_rect(width, length, min(width, length) * 0.42, 8, center=(cx, -cz))
            sole = Part(
                id=f"sole_{tag}", shape=Extrude(profile=Profile(sole_outline), depth=p.shoe_sole, axis="y"),
                material="rubber", modifiers=(Bevel(width=0.004, segments=2),), smooth_angle=math.radians(40),
                parent_joint=f"{tag}_subtalar",
            )
            ankle_cx = (foot["ankle_x"][0] + foot["ankle_x"][1]) / 2
            ankle_cz = (foot["ankle_z"][0] + foot["ankle_z"][1]) / 2
            ankle_w = foot["ankle_x"][1] - foot["ankle_x"][0] + 0.012
            ankle_d = foot["ankle_z"][1] - foot["ankle_z"][0] + 0.014
            # The loft is the upper's inner surface (6 mm clearance over the foot, toes covered to 3 cm);
            # Solidify grows the 6 mm shell outward so the foot never pokes through.
            inner_w, inner_l = width - 0.012, length - 0.004
            upper_sections = (
                LoftSection(ellipse(inner_w, inner_l), Transform(translation=(cx, lift - 0.010, cz))),
                LoftSection(ellipse(inner_w, inner_l), Transform(translation=(cx, lift + 0.016, cz))),
                LoftSection(ellipse(inner_w - 0.004, inner_l - 0.012), Transform(translation=(cx, lift + 0.032, cz - 0.004))),
                LoftSection(ellipse(inner_w - 0.010, inner_l - 0.05), Transform(translation=(cx, lift + 0.048, cz - 0.02))),
                LoftSection(ellipse(ankle_w + 0.016, ankle_d + 0.05), Transform(translation=(ankle_cx, lift + 0.064, ankle_cz + 0.015))),
                LoftSection(ellipse(ankle_w + 0.006, ankle_d + 0.006), Transform(translation=(ankle_cx, lift + 0.080, ankle_cz))),
            )
            upper = Part(
                id=f"shoe_{tag}", shape=Loft(sections=upper_sections, capped=False), material="canvas",
                modifiers=(Subdivision(levels=1, smooth=True), Solidify(thickness=0.006, offset=1.0)),
                smooth_angle=math.radians(60), parent_joint=f"{tag}_subtalar",
            )
            # Laces: five eyelet pairs along the instep line (the front of the loft rings), criss-crossed.
            instep = [  # (y, z) of the upper's outer top surface from the toe box back to the collar
                (lift + 0.022, cz + inner_l / 2 + 0.006),
                (lift + 0.038, cz - 0.004 + (inner_l - 0.012) / 2 + 0.006),
                (lift + 0.054, cz - 0.02 + (inner_l - 0.05) / 2 + 0.006),
                (lift + 0.070, ankle_cz + 0.015 + (ankle_d + 0.05) / 2 + 0.006),
                (lift + 0.086, ankle_cz + (ankle_d + 0.006) / 2 + 0.006),
            ]

            def instep_y(z: float) -> float:
                for (y0, za), (y1, zb) in zip(instep, instep[1:]):
                    if zb <= z <= za:
                        return y0 + (y1 - y0) * (za - z) / (za - zb)
                return instep[-1][0]

            eyelets = []
            z_first, z_last = instep[1][1] - 0.008, instep[3][1] + 0.004
            for k in range(5):
                f = k / 4
                ez = z_first + (z_last - z_first) * f
                ey = instep_y(ez) + 0.002
                half = 0.014 - 0.003 * f
                eyelets.append(((cx - half, ey, ez), (cx + half, ey, ez)))
            laces = []
            lace_profile = Profile(curves.circle(0.002, 8))
            for k in range(4):
                (l0, r0), (l1, r1) = eyelets[k], eyelets[k + 1]
                for a, b in ((l0, r1), (r0, l1)):
                    mid = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2 + 0.004, (a[2] + b[2]) / 2)
                    laces.append(Sweep(profile=lace_profile, path=((a[0], a[1] + 0.002, a[2]), mid, (b[0], b[1] + 0.002, b[2])), capped=True))
            (l4, r4) = eyelets[4]
            laces.append(Sweep(profile=lace_profile, path=((l4[0], l4[1] + 0.003, l4[2]), (cx, l4[1] + 0.006, l4[2] - 0.004), (r4[0], r4[1] + 0.003, r4[2])), capped=True))
            lace_part = Part(id=f"laces_{tag}", shape=Strands(strands=tuple(laces)), material="lace",
                             smooth_angle=math.radians(60), parent_joint=f"{tag}_subtalar")
            shoe_parts += [sole, upper, lace_part]

    # --- poses and clips (authoring/world axes; MHR rests in an A-pose, arms about 40 degrees down) ----
    W = "world"

    def rot(x: float = 0.0, y: float = 0.0, z: float = 0.0, translation=(0.0, 0.0, 0.0)) -> JointTransform:
        return JointTransform(rotation=(math.radians(x), math.radians(y), math.radians(z)), translation=translation, space=W)

    # Relaxed hands: fingers curl in their own joint frames (MHR rests with fingers straight); the thumb
    # is already abducted in the rest pose. Every pose carries these so the hands never snap open.
    hands: dict[str, JointTransform] = {}
    for side in ("l", "r"):
        for finger, curl in (("index", (22, 28, 18)), ("middle", (26, 32, 20)), ("ring", (30, 34, 22)), ("pinky", (34, 36, 24))):
            for segment, angle in zip((1, 2, 3), curl):
                hands[f"{side}_{finger}{segment}"] = JointTransform(rotation=(math.radians(angle), 0.0, 0.0))
        for segment, angle in zip((1, 2, 3), (8, 14, 10)):
            hands[f"{side}_thumb{segment}"] = JointTransform(rotation=(math.radians(angle), 0.0, 0.0))

    def pose(pose_id: str, joints: dict, shapes: dict | None = None) -> Pose:
        return Pose(pose_id, {**hands, **joints}, shapes=shapes or {})

    rest = pose("rest", {})
    raise_arms = pose("raise_arms", {"r_uparm": rot(z=-95), "l_uparm": rot(z=95)})
    step_r = pose("step_r", {"r_upleg": rot(x=28), "l_upleg": rot(x=-22), "l_lowleg": rot(x=-30),
                             "r_uparm": rot(x=-20), "l_uparm": rot(x=24)})
    step_l = pose("step_l", {"l_upleg": rot(x=28), "r_upleg": rot(x=-22), "r_lowleg": rot(x=-30),
                             "l_uparm": rot(x=-20), "r_uparm": rot(x=24)})
    breathe = pose("breathe", {"c_spine3": rot(x=-2.0, translation=(0.0, 0.004, 0.0)), "c_head": rot(x=1.5)})
    sit = pose("sit", {
        "root": rot(translation=(0.0, -0.36, 0.0)),
        "l_upleg": rot(x=88), "r_upleg": rot(x=88), "l_lowleg": rot(x=-90), "r_lowleg": rot(x=-90),
        "c_spine1": rot(x=4), "l_uparm": rot(x=12), "r_uparm": rot(x=12),
    })
    turn_90 = pose("turn_90", {"root": rot(y=90)})
    turn_180 = pose("turn_180", {"root": rot(y=180)})
    # Blueprint QA: knee 120, elbow 135, hip 90, shoulder elevation 150 (arm 110 degrees above the A-pose).
    range_check = pose("range_check", {
        "l_upleg": rot(x=90), "l_lowleg": rot(x=-120), "r_lowarm": rot(z=-135), "r_uparm": rot(z=-110),
    })
    gaze_left = pose("gaze_left", {"l_eye": rot(y=18), "r_eye": rot(y=18), "c_head": rot(y=6)})
    # Face shapes come from MHR's expression parameters (promodeler.human.mhr.FACE_SHAPES) as shape keys.
    blink = pose("blink", {}, {"blink_l": 1.0, "blink_r": 1.0})
    smile = pose("smile", {}, {"smile": 1.0, "blink_l": 0.15, "blink_r": 0.15})
    mouth_open = pose("mouth_open", {}, {"jaw_open": 1.0})
    vowels = tuple(pose(f"vowel_{v}", {}, {f"vowel_{v}": 1.0}) for v in "aiueo")
    talk = pose("talk", {"c_head": rot(x=-2)}, {"vowel_a": 0.6, "smile": 0.3})
    clips = (
        Clip("idle", duration=4.0, keyframes=(Keyframe(0.0, "rest"), Keyframe(1.0, "rest"), Keyframe(1.1, "blink"),
                                              Keyframe(1.25, "rest"), Keyframe(2.0, "breathe"), Keyframe(4.0, "rest"))),
        Clip("speak", duration=2.0, loop=False, keyframes=(
            Keyframe(0.0, "rest"), Keyframe(0.3, "vowel_a"), Keyframe(0.6, "vowel_i"), Keyframe(0.9, "vowel_u"),
            Keyframe(1.2, "vowel_e"), Keyframe(1.5, "vowel_o"), Keyframe(1.8, "smile"), Keyframe(2.0, "rest"))),
        Clip("walk", duration=1.2, keyframes=(Keyframe(0.0, "step_r"), Keyframe(0.6, "step_l"), Keyframe(1.2, "step_r"))),
        Clip("turn", duration=2.0, loop=False,
             keyframes=(Keyframe(0.0, "rest"), Keyframe(1.0, "turn_90"), Keyframe(2.0, "turn_180"))),
        Clip("sit", duration=3.0, loop=False, keyframes=(Keyframe(0.0, "rest"), Keyframe(2.4, "sit"), Keyframe(3.0, "sit"))),
        Clip("raise-arms", duration=3.0, loop=False,
             keyframes=(Keyframe(0.0, "rest"), Keyframe(1.5, "raise_arms"), Keyframe(3.0, "rest"))),
        Clip("physics-settle", duration=6.0, loop=False,
             keyframes=(Keyframe(0.0, "rest"), Keyframe(2.0, "rest"), Keyframe(2.3, "step_r"), Keyframe(2.9, "step_l"),
                        Keyframe(3.5, "step_r"), Keyframe(4.0, "rest"), Keyframe(6.0, "rest"))),
    )
    # Deliverables the GLB cannot carry: the blueprint's runtime physics settings and engine targets.
    extras = {
        "blueprint": {"folder": blueprint["folder"], "id": blueprint["id"], "schema": blueprint["schema"]},
        "physics": blueprint.get("physics", {}),
        "target": blueprint.get("target", {}),
        "fit": {k: round(v, 4) for k, v in fit["measurements"].items()},
        "hair_guides": guides,  # low-resolution dynamics guides separated from the bundle meshes
    }
    return Asset(
        name="Haruka", materials=(skin, hair, cloth, rubber, canvas, lace, eye),
        parts=(body, dress, hair_cap_part, hair_strands, *eyeballs, *shoe_parts), rig=rig,
        poses=(rest, raise_arms, step_r, step_l, breathe, sit, turn_90, turn_180, range_check, gaze_left,
               blink, smile, mouth_open, *vowels, talk), clips=clips,
        extras=extras,
    )


asset = AssetGenerator(name="Haruka", parameters=HarukaParameters(), build=build, validate=validate, seed=23,
                       quality=QualityProfile(texture_resolution=2048))
LIFT = HarukaParameters().shoe_sole
render = RenderSettings(
    resolution=768, views=("front", "side", "back", "perspective"), passes=("shaded", "clay"),
    cameras=(
        Camera("face", position=(0.0, 1.50 + LIFT, 0.75), target=(0.0, 1.49 + LIFT, 0.06), fov=math.radians(22)),
        Camera("neckline", position=(0.0, 1.28 + LIFT, 0.85), target=(0.0, 1.24 + LIFT, 0.1), fov=math.radians(24)),
        Camera("sneaker", position=(0.55, 0.32, 0.55), target=(0.18, 0.05, 0.0), fov=math.radians(28)),
        Camera("hand", position=(0.90, 0.92 + LIFT, 0.55), target=(0.58, 0.99 + LIFT, 0.16), fov=math.radians(16)),
    ),
)
