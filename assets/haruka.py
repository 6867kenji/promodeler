"""Haruka (blueprints/japan-realistic-v1/05-woman), body v0: a dimension-accurate mannequin.

What this version is: torso, head, limbs and chest built from the
blueprint's cross sections and joint positions, fused into one skinned
body, an A-pose rig with the blueprint's 21 joints, a cloth-draped
sleeveless dress, a hair mass and three verification clips.

What it is not yet: a face, hands with fingers, toes, facial morphs,
runtime physics or the sneakers. Those are listed in the blueprint as
separate work and stay open.

Run:  python -m promodeler build assets/haruka.py --texture-resolution 512 --bake-samples 8
Pose check:  --pose raise_arms --views front,side
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from promodeler.core import (
    Asset, AssetGenerator, Bevel, Boolean, Clip, ClothDrape, Cutter, Cylinder, Extrude, GenerationInput, Joint,
    JointTransform, Keyframe, Layer, Loft, LoftSection, Material, ModelingError, Noise, Part, Pose, Position,
    Profile, RenderSettings, Rig, Sphere, Subdivision, Solidify, Transform, curves, srgb,
)

# --- blueprint numbers (05-woman/blueprint.json) ---------------------------------
HEIGHT = 1.600
INSEAM = 0.735
HEAD_HEIGHT = 0.218
SHOULDER_WIDTH = 0.36
CROSS_SECTIONS = {  # landmark: (height, width, depth)
    "hip": (0.95, 0.285, 0.205),
    "waist": (1.06, 0.225, 0.155),
    "underbust": (1.18, 0.27, 0.195),
    "bust": (1.25, 0.305, 0.255),
    "shoulders": (1.34, 0.36, 0.18),
    "neck": (1.405, 0.105, 0.105),
    "head": (1.49, 0.145, 0.17),
}
JOINTS = [  # id, parent, head, tail (authoring space, meters)
    ("root", None, (0, 0, 0), (0, 0.01, 0)),
    ("pelvis", "root", (0, 0.87, 0), (0, 0.97, 0)),
    ("spine01", "pelvis", (0, 0.97, 0), (0, 1.1, 0)),
    ("spine02", "spine01", (0, 1.1, 0), (0, 1.22, 0)),
    ("chest", "spine02", (0, 1.22, 0), (0, 1.34, 0)),
    ("neck", "chest", (0, 1.34, 0), (0, 1.405, 0)),
    ("head", "neck", (0, 1.405, 0), (0, 1.6, 0)),
    ("clavicle.R", "chest", (-0.04, 1.33, 0), (-0.18, 1.32, 0)),
    ("upperarm.R", "clavicle.R", (-0.18, 1.32, 0), (-0.33, 1.1, 0)),
    ("forearm.R", "upperarm.R", (-0.33, 1.1, 0), (-0.46, 0.91, 0.015)),
    ("hand.R", "forearm.R", (-0.46, 0.91, 0.015), (-0.53, 0.81, 0.02)),
    ("thigh.R", "pelvis", (-0.085, 0.87, 0), (-0.085, 0.47, 0.015)),
    ("shin.R", "thigh.R", (-0.085, 0.47, 0.015), (-0.085, 0.075, 0)),
    ("foot.R", "shin.R", (-0.085, 0.075, 0), (-0.085, 0.04, 0.17)),
    ("clavicle.L", "chest", (0.04, 1.33, 0), (0.18, 1.32, 0)),
    ("upperarm.L", "clavicle.L", (0.18, 1.32, 0), (0.33, 1.1, 0)),
    ("forearm.L", "upperarm.L", (0.33, 1.1, 0), (0.46, 0.91, 0.015)),
    ("hand.L", "forearm.L", (0.46, 0.91, 0.015), (0.53, 0.81, 0.02)),
    ("thigh.L", "pelvis", (0.085, 0.87, 0), (0.085, 0.47, 0.015)),
    ("shin.L", "thigh.L", (0.085, 0.47, 0.015), (0.085, 0.075, 0)),
    ("foot.L", "shin.L", (0.085, 0.075, 0), (0.085, 0.04, 0.17)),
]


@dataclass(frozen=True)
class HarukaParameters:
    height: float = HEIGHT
    dress_hem_height: float = 0.48
    hair_length: float = 0.66
    cloth_frames: int = 60


def validate(p: HarukaParameters) -> None:
    if not 1.4 <= p.height <= 1.9:
        raise ModelingError("haruka.height", "height must be 1.4...1.9 m.")
    if not 0.3 <= p.dress_hem_height <= 0.9:
        raise ModelingError("haruka.hem", "dress_hem_height must be 0.3...0.9 m.")
    if not 0.1 <= p.hair_length <= 1.0:
        raise ModelingError("haruka.hair", "hair_length must be 0.1...1 m.")
    if not 10 <= p.cloth_frames <= 240:
        raise ModelingError("haruka.cloth", "cloth_frames must be 10...240.")


SEGMENTS = 40


def ellipse(width: float, depth: float, points: int = SEGMENTS):
    return tuple((u * width / 2, v * depth / 2) for u, v in curves.circle(1.0, points))


def section(width: float, depth: float, y: float, z: float = 0.0) -> LoftSection:
    return LoftSection(ellipse(width, depth), Transform(translation=(0.0, y, z)))


def limb(radii: list[tuple[float, float, float]]) -> Loft:
    """Sections (t along +Y in meters, width, depth) stacked from the joint head outward."""
    return Loft(sections=tuple(section(w, d, t) for t, w, d in radii), capped=True)


def align_y(head, tail) -> Transform:
    """Rotate local +Y onto the head->tail direction (in the XY plane) and place at the head."""
    dx, dy = tail[0] - head[0], tail[1] - head[1]
    angle = math.atan2(-dx, dy)
    return Transform(translation=head, rotation=(0.0, 0.0, angle))


def torso() -> Loft:
    s = CROSS_SECTIONS
    sections = (
        section(0.24, 0.17, INSEAM + 0.02, 0.0),
        section(0.275, 0.195, 0.87, 0.0),
        section(*s["hip"][1:], s["hip"][0], 0.0),
        section(0.255, 0.18, 1.0, 0.0),
        section(*s["waist"][1:], s["waist"][0], 0.0),
        section(0.245, 0.17, 1.12, 0.0),
        section(*s["underbust"][1:], s["underbust"][0], 0.0),
        section(0.285, 0.21, 1.22, 0.0),
        section(0.30, 0.20, 1.28, 0.0),
        section(0.33, 0.185, 1.32, 0.0),
        section(*s["shoulders"][1:], s["shoulders"][0], 0.0),
        section(0.28, 0.15, 1.375, 0.0),
        section(0.14, 0.12, 1.40, 0.0),
    )
    return Loft(sections=sections, capped=True)


def head() -> Loft:
    chin = HEIGHT - HEAD_HEIGHT
    sections = (
        section(0.07, 0.08, chin, 0.02),
        section(0.11, 0.135, chin + 0.03, 0.005),
        section(0.135, 0.165, chin + 0.075, -0.005),
        section(0.145, 0.17, 1.49, -0.01),
        section(0.14, 0.165, 1.54, -0.012),
        section(0.11, 0.135, 1.58, -0.015),
        section(0.05, 0.06, HEIGHT, -0.02),
    )
    return Loft(sections=sections, capped=True)


def build(input: GenerationInput) -> Asset:
    p: HarukaParameters = input.parameters
    seed = input.seed
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

    joints = tuple(Joint(jid, head=h, tail=t, parent=parent) for jid, parent, h, t in JOINTS)
    by_id = {j.id: j for j in joints}
    rig = Rig("haruka", joints=joints)

    def limb_cutter(joint_id: str, radii, extra: Transform | None = None) -> Cutter:
        j = by_id[joint_id]
        return Cutter(shape=limb(radii), transform=align_y(j.head, j.tail))

    unions = []
    # Neck and head.
    unions.append(Cutter(shape=Cylinder(radius=0.0525, height=0.10, segments=32),
                         transform=Transform(translation=(0.0, 1.40, 0.0))))
    unions.append(Cutter(shape=head()))
    # Chest volumes.
    for x in (-0.075, 0.075):
        unions.append(Cutter(shape=Sphere(radius=0.068, segments=32, rings=16),
                             transform=Transform(translation=(x, 1.245, 0.085), scale=(1.0, 0.9, 0.8))))
    # Arms in A-pose, sections along the joint from shoulder to fingertip.
    for side in ("R", "L"):
        unions.append(limb_cutter(f"upperarm.{side}", [(-0.03, 0.10, 0.10), (0.0, 0.105, 0.105), (0.13, 0.085, 0.085), (0.266, 0.07, 0.072)]))
        unions.append(limb_cutter(f"forearm.{side}", [(-0.01, 0.072, 0.074), (0.11, 0.064, 0.066), (0.23, 0.05, 0.052)]))
        unions.append(limb_cutter(f"hand.{side}", [(-0.005, 0.05, 0.03), (0.04, 0.085, 0.032), (0.10, 0.08, 0.028), (0.122, 0.04, 0.02)]))
        unions.append(limb_cutter(f"thigh.{side}", [(-0.05, 0.17, 0.19), (0.0, 0.168, 0.188), (0.2, 0.135, 0.15), (0.40, 0.11, 0.115)]))
        unions.append(limb_cutter(f"shin.{side}", [(-0.02, 0.11, 0.115), (0.11, 0.12, 0.13), (0.30, 0.08, 0.09), (0.395, 0.07, 0.075)]))
        x = -0.085 if side == "R" else 0.085
        foot_outline = curves.rounded_rect(0.09, 0.235, 0.035, 6, center=(0.0, 0.0675))
        unions.append(Cutter(shape=Extrude(profile=Profile(foot_outline), depth=0.07, axis="y"),
                             transform=Transform(translation=(x, 0.0, 0.0)),
                             modifiers=(Bevel(width=0.02, segments=3),)))

    body = Part(
        id="body",
        shape=torso(),
        material="skin",
        modifiers=tuple(Boolean("union", cutter=c) for c in unions),
        smooth_angle=math.radians(50),
        skinned=True,
    )

    # Dress: a fitted tube with an A-line skirt, pinned at the shoulders and draped by cloth simulation.
    hem_flare = 0.42
    dress_sections = (
        section(0.31, 0.235, 1.30),
        section(0.335, 0.28, 1.25),
        section(0.30, 0.225, 1.18),
        section(0.255, 0.185, 1.06),
        section(0.32, 0.24, 0.95),
        section(hem_flare * 0.9, hem_flare * 0.75, 0.75),
        section(hem_flare, hem_flare * 0.85, p.dress_hem_height),
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

    # Hair: a cap over the skull and a mass falling down the back to the hair length.
    top = HEIGHT + 0.012
    hair_cap = Loft(sections=(
        section(0.06, 0.07, top, -0.02),
        section(0.13, 0.15, top - 0.03, -0.02),
        section(0.165, 0.195, top - 0.09, -0.02),
        section(0.17, 0.2, top - 0.15, -0.025),
        section(0.165, 0.19, top - 0.21, -0.03),
    ), capped=True)
    hair_tip = HEIGHT - p.hair_length
    hair_back = Loft(sections=(
        section(0.20, 0.09, 1.50, -0.085),
        section(0.24, 0.085, 1.36, -0.10),
        section(0.27, 0.075, 1.20, -0.125),
        section(0.26, 0.06, 1.05, -0.13),
        section(0.20, 0.04, hair_tip, -0.125),
    ), capped=True)
    hair_part = Part(
        id="hair",
        shape=hair_cap,
        material="hair",
        modifiers=(Boolean("union", cutter=Cutter(shape=hair_back)),),
        smooth_angle=math.radians(50),
        skinned=True,
    )

    # Verification poses in authoring (world) axes: Z raises an arm sideways, X swings limbs forward and back.
    W = "world"
    raise_arms = Pose("raise_arms", {
        "upperarm.R": JointTransform(rotation=(0.0, 0.0, math.radians(-110)), space=W),
        "upperarm.L": JointTransform(rotation=(0.0, 0.0, math.radians(110)), space=W),
    })
    step_r = Pose("step_r", {
        "thigh.R": JointTransform(rotation=(math.radians(28), 0.0, 0.0), space=W),
        "thigh.L": JointTransform(rotation=(math.radians(-22), 0.0, 0.0), space=W),
        "shin.L": JointTransform(rotation=(math.radians(-30), 0.0, 0.0), space=W),
        "upperarm.R": JointTransform(rotation=(math.radians(-20), 0.0, 0.0), space=W),
        "upperarm.L": JointTransform(rotation=(math.radians(24), 0.0, 0.0), space=W),
    })
    step_l = Pose("step_l", {
        "thigh.L": JointTransform(rotation=(math.radians(28), 0.0, 0.0), space=W),
        "thigh.R": JointTransform(rotation=(math.radians(-22), 0.0, 0.0), space=W),
        "shin.R": JointTransform(rotation=(math.radians(-30), 0.0, 0.0), space=W),
        "upperarm.L": JointTransform(rotation=(math.radians(-20), 0.0, 0.0), space=W),
        "upperarm.R": JointTransform(rotation=(math.radians(24), 0.0, 0.0), space=W),
    })
    breathe = Pose("breathe", {
        "chest": JointTransform(rotation=(math.radians(-2.0), 0.0, 0.0), translation=(0.0, 0.004, 0.0), space=W),
        "head": JointTransform(rotation=(math.radians(1.5), 0.0, 0.0), space=W),
    })
    clips = (
        Clip("idle", duration=4.0, keyframes=(Keyframe(0.0, None), Keyframe(2.0, "breathe"), Keyframe(4.0, None))),
        Clip("walk", duration=1.2, keyframes=(Keyframe(0.0, "step_r"), Keyframe(0.6, "step_l"), Keyframe(1.2, "step_r"))),
        Clip("raise-arms", duration=3.0, loop=False,
             keyframes=(Keyframe(0.0, None), Keyframe(1.5, "raise_arms"), Keyframe(3.0, None))),
    )
    return Asset(
        name="Haruka", materials=(skin, hair, cloth), parts=(body, dress, hair_part), rig=rig,
        poses=(raise_arms, step_r, step_l, breathe), clips=clips,
    )


asset = AssetGenerator(name="Haruka", parameters=HarukaParameters(), build=build, validate=validate, seed=23)
render = RenderSettings(resolution=768, views=("front", "side", "back", "perspective"), passes=("shaded", "clay"))
