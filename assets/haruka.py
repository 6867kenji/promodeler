"""Haruka (blueprints/japan-realistic-v1/05-woman), body v1: Meta MHR body fitted to the blueprint.

The body is no longer a loft mannequin. ``promodeler.human.mhr`` fits
Meta's Momentum Human Rig (skeletal scales + identity coefficients) to the
blueprint's height, inseam, shoulder width, foot and head sizes and the
bust/underbust/waist/hip circumferences, then exports the LOD1 mesh with
UVs, skin weights and the 126-joint skeleton. This file loads that export
through ``MeshFile`` and ``rig_from_file`` and adds what MHR does not
provide: skin/hair/cloth materials, a cloth-draped dress fitted to the
measured torso, a hair mass fitted to the measured skull, and the
verification poses and clips in MHR joint names.

Still open: face identity (MHR head coefficients), hand poses, toes and
the sneakers from the blueprint.

Run:  python -m promodeler build assets/haruka.py --texture-resolution 512 --bake-samples 8
Pose check:  --pose raise_arms --views front,side
First build fits the body (about 40 s, torch on CPU); later builds reuse build/human/haruka-*.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from promodeler.core import (
    Asset, AssetGenerator, Clip, ClothDrape, GenerationInput, JointTransform, Keyframe, Layer, Loft, LoftSection,
    Material, MeshFile, ModelingError, Noise, Part, Pose, Position, RenderSettings, Solidify, Subdivision, Transform,
    curves, srgb,
)
from promodeler.human.mhr import blueprint_targets, fitted_body, rig_from_file

ROOT = Path(__file__).resolve().parent.parent
BLUEPRINT = ROOT / "blueprints" / "japan-realistic-v1" / "05-woman" / "blueprint.json"


@dataclass(frozen=True)
class HarukaParameters:
    dress_hem_height: float = 0.48
    dress_ease: float = 0.03  # extra width/depth over the measured torso, meters
    hair_length: float = 0.66
    hair_thickness: float = 0.012
    cloth_frames: int = 60


def validate(p: HarukaParameters) -> None:
    if not 0.3 <= p.dress_hem_height <= 0.9:
        raise ModelingError("haruka.hem", "dress_hem_height must be 0.3...0.9 m.")
    if not 0.0 <= p.dress_ease <= 0.15:
        raise ModelingError("haruka.ease", "dress_ease must be 0...0.15 m.")
    if not 0.1 <= p.hair_length <= 1.0:
        raise ModelingError("haruka.hair", "hair_length must be 0.1...1 m.")
    if not 0.004 <= p.hair_thickness <= 0.05:
        raise ModelingError("haruka.hairThickness", "hair_thickness must be 4...50 mm.")
    if not 10 <= p.cloth_frames <= 240:
        raise ModelingError("haruka.cloth", "cloth_frames must be 10...240.")


SEGMENTS = 40


def ellipse(width: float, depth: float, points: int = SEGMENTS):
    return tuple((u * width / 2, v * depth / 2) for u, v in curves.circle(1.0, points))


def section(width: float, depth: float, y: float, z: float = 0.0) -> LoftSection:
    return LoftSection(ellipse(width, depth), Transform(translation=(0.0, y, z)))


class BodyMeasure:
    """Horizontal slices of the fitted body, used to fit clothing and hair to the actual surface."""

    def __init__(self, mesh_path: str) -> None:
        self.vertices = np.load(mesh_path)["vertices"].astype(float)
        self.height = float(self.vertices[:, 1].max())

    def slice(self, y: float, x_limit: float = 0.2, band: float = 0.012) -> tuple[float, float, float]:
        """(width, depth, z center) of the vertices within ``band`` of height ``y`` and ``|x| < x_limit``."""
        v = self.vertices
        s = v[(np.abs(v[:, 1] - y) < band) & (np.abs(v[:, 0]) < x_limit)]
        if len(s) < 8:
            raise ModelingError("haruka.slice", f"No body surface at height {y:.3f} m.")
        width = float(s[:, 0].max() - s[:, 0].min())
        depth = float(s[:, 2].max() - s[:, 2].min())
        return width, depth, float((s[:, 2].max() + s[:, 2].min()) / 2)

    def fitted_section(self, y: float, ease: float, x_limit: float = 0.2, z_shift: float = 0.0) -> LoftSection:
        width, depth, zc = self.slice(y, x_limit)
        return section(width + ease, depth + ease, y, zc + z_shift)


def build(input: GenerationInput) -> Asset:
    p: HarukaParameters = input.parameters
    seed = input.seed

    blueprint = json.loads(BLUEPRINT.read_text(encoding="utf-8"))
    fit = fitted_body(blueprint_targets(blueprint), out_root=ROOT / "build" / "human", name="haruka")
    measure = BodyMeasure(fit["mesh"])
    height = measure.height

    skin = Material(
        "skin", base_color=srgb(0.922, 0.824, 0.765), roughness=0.42 + Noise(size=0.02, detail=3.0, seed=seed) * 0.13,
        height=Noise(size=0.0008, detail=2.0, roughness=0.6, seed=seed + 1) * 0.00004,
        layers=(Layer(base_color=srgb(0.86, 0.68, 0.64), mask=(Noise(size=0.08, detail=2.0, seed=seed + 2) * 0.35).clamp()),),
        bump_strength=1.0,
    )
    hair = Material(
        "hair", base_color=srgb(0.19, 0.125, 0.106), roughness=0.3 + Noise(size=(0.004, 0.25, 0.004), detail=3.0, seed=seed + 3) * 0.15,
        height=Noise(size=(0.002, 0.3, 0.002), detail=2.0, seed=seed + 4) * 0.0003, bump_strength=1.5,
    )
    cloth = Material(
        "cloth", base_color=srgb(0.718, 0.769, 0.698), roughness=0.75 + Noise(size=0.0025, detail=4.0, seed=seed + 5) * 0.1,
        height=Noise(size=(0.0006, 0.0006, 0.0006), detail=2.0, seed=seed + 6) * 0.00005, bump_strength=1.2,
    )

    rig = rig_from_file(fit["rig"], rig_id="haruka")

    body = Part(
        id="body",
        shape=MeshFile(fit["mesh"]),
        material="skin",
        smooth_angle=math.radians(60),
        skinned=True,
    )

    # Dress: fitted tube over the measured torso, A-line skirt, pinned under the arms and draped by cloth simulation.
    ease = p.dress_ease
    hem_flare = 0.42
    torso_heights = (1.30, 1.25, 1.18, 1.06, 0.95)
    dress_sections = tuple(measure.fitted_section(y, ease) for y in torso_heights)
    _, _, hip_z = measure.slice(0.95)
    dress_sections += (
        section(hem_flare * 0.9, hem_flare * 0.75, 0.75, hip_z),
        section(hem_flare, hem_flare * 0.85, p.dress_hem_height, hip_z),
    )
    dress = Part(
        id="dress",
        shape=Loft(sections=dress_sections, capped=False),
        material="cloth",
        modifiers=(
            Subdivision(levels=2, smooth=False),
            ClothDrape(frames=p.cloth_frames, mass=0.14, stiffness=10.0, bending=0.08, damping=6.0, quality=6,
                       thickness=0.004, pin=Position("y", 1.20, 1.28)),
            Solidify(thickness=0.0015, offset=0.0),
        ),
        smooth_angle=math.radians(60),
        skinned=True,
    )

    # Hair: a cap following the measured skull plus a mass falling down the back to the hair length.
    t = p.hair_thickness * 2
    top = height + p.hair_thickness
    # The cap stops above the brow (about 0.09 m below the crown); its lowest ring is pulled back so the
    # face stays uncovered while the sides and back still wrap the skull.
    _, _, crown_z = measure.slice(height - 0.03, x_limit=0.12)
    _, brow_depth, brow_z = measure.slice(height - 0.09, x_limit=0.12)
    brow_width, _, _ = measure.slice(height - 0.09, x_limit=0.12)
    hair_cap = Loft(sections=(
        section(brow_width + t, brow_depth * 0.75 + t, height - 0.10, brow_z - brow_depth * 0.14),
        measure.fitted_section(height - 0.07, t, x_limit=0.12),
        measure.fitted_section(height - 0.03, t, x_limit=0.12),
        section(0.05, 0.06, top, crown_z),
    ), capped=True)
    _, head_depth, head_z = measure.slice(height - 0.10, x_limit=0.12)
    back = head_z - head_depth / 2  # z of the back of the skull
    _, shoulder_depth, shoulder_z = measure.slice(1.30)
    shoulder_back = shoulder_z - shoulder_depth / 2
    hair_tip = height - p.hair_length
    hair_back = Loft(sections=(
        section(0.20, 0.04, hair_tip, shoulder_back - 0.04),
        section(0.26, 0.06, 1.05, shoulder_back - 0.045),
        section(0.27, 0.075, 1.20, shoulder_back - 0.04),
        section(0.24, 0.085, 1.36, shoulder_back - 0.02),
        section(0.20, 0.09, height - 0.10, back - 0.02),
    ), capped=True)
    hair_cap_part = Part(id="hair", shape=hair_cap, material="hair", smooth_angle=math.radians(50), skinned=True)
    hair_back_part = Part(id="hair_back", shape=hair_back, material="hair", smooth_angle=math.radians(50), skinned=True)

    # Verification poses in authoring (world) axes: Z raises an arm sideways, X swings limbs forward and back.
    # MHR rests in an A-pose with the arms about 40 degrees below horizontal.
    W = "world"
    raise_arms = Pose("raise_arms", {
        "r_uparm": JointTransform(rotation=(0.0, 0.0, math.radians(-95)), space=W),
        "l_uparm": JointTransform(rotation=(0.0, 0.0, math.radians(95)), space=W),
    })
    step_r = Pose("step_r", {
        "r_upleg": JointTransform(rotation=(math.radians(28), 0.0, 0.0), space=W),
        "l_upleg": JointTransform(rotation=(math.radians(-22), 0.0, 0.0), space=W),
        "l_lowleg": JointTransform(rotation=(math.radians(-30), 0.0, 0.0), space=W),
        "r_uparm": JointTransform(rotation=(math.radians(-20), 0.0, 0.0), space=W),
        "l_uparm": JointTransform(rotation=(math.radians(24), 0.0, 0.0), space=W),
    })
    step_l = Pose("step_l", {
        "l_upleg": JointTransform(rotation=(math.radians(28), 0.0, 0.0), space=W),
        "r_upleg": JointTransform(rotation=(math.radians(-22), 0.0, 0.0), space=W),
        "r_lowleg": JointTransform(rotation=(math.radians(-30), 0.0, 0.0), space=W),
        "l_uparm": JointTransform(rotation=(math.radians(-20), 0.0, 0.0), space=W),
        "r_uparm": JointTransform(rotation=(math.radians(24), 0.0, 0.0), space=W),
    })
    breathe = Pose("breathe", {
        "c_spine3": JointTransform(rotation=(math.radians(-2.0), 0.0, 0.0), translation=(0.0, 0.004, 0.0), space=W),
        "c_head": JointTransform(rotation=(math.radians(1.5), 0.0, 0.0), space=W),
    })
    clips = (
        Clip("idle", duration=4.0, keyframes=(Keyframe(0.0, None), Keyframe(2.0, "breathe"), Keyframe(4.0, None))),
        Clip("walk", duration=1.2, keyframes=(Keyframe(0.0, "step_r"), Keyframe(0.6, "step_l"), Keyframe(1.2, "step_r"))),
        Clip("raise-arms", duration=3.0, loop=False,
             keyframes=(Keyframe(0.0, None), Keyframe(1.5, "raise_arms"), Keyframe(3.0, None))),
    )
    return Asset(
        name="Haruka", materials=(skin, hair, cloth), parts=(body, dress, hair_cap_part, hair_back_part), rig=rig,
        poses=(raise_arms, step_r, step_l, breathe), clips=clips,
    )


asset = AssetGenerator(name="Haruka", parameters=HarukaParameters(), build=build, validate=validate, seed=23)
render = RenderSettings(resolution=768, views=("front", "side", "back", "perspective"), passes=("shaded", "clay"))
