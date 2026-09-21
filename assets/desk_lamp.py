"""M5 example: an articulated desk lamp with rigid parts attached to joints and a "nod" clip.

Run:  python -m promodeler build assets/desk_lamp.py --pose nod_down
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from promodeler.core import (
    Asset, AssetGenerator, Bevel, Clip, Cone, Cylinder, GenerationInput, Joint, JointTransform, Keyframe,
    ModelingError, Part, Pose, RenderSettings, Revolve, Rig, Transform, presets, srgb, Material,
)


@dataclass(frozen=True)
class LampParameters:
    arm_length: float = 0.28
    forearm_length: float = 0.24


def validate(p: LampParameters) -> None:
    for name in ("arm_length", "forearm_length"):
        if not 0.1 <= getattr(p, name) <= 0.6:
            raise ModelingError("lamp.length", f"{name} must be 10...60 cm.")


def build(input: GenerationInput) -> Asset:
    p: LampParameters = input.parameters
    paint = presets.painted_metal("paint", color=srgb(0.15, 0.32, 0.22), seed=input.seed, wear=0.5, edge_radius=0.006)
    steel = Material("steel", base_color=srgb(0.7, 0.7, 0.72), roughness=0.35, metallic=1.0)
    base_height = 0.03
    elbow = base_height + p.arm_length
    head = elbow + p.forearm_length
    rig = Rig("lamp", joints=(
        Joint("j_base", head=(0.0, 0.0, 0.0), tail=(0.0, base_height, 0.0)),
        Joint("j_arm", head=(0.0, base_height, 0.0), tail=(0.0, elbow, 0.0), parent="j_base"),
        Joint("j_forearm", head=(0.0, elbow, 0.0), tail=(0.0, head, 0.0), parent="j_arm"),
        Joint("j_head", head=(0.0, head, 0.0), tail=(0.0, head + 0.05, 0.0), parent="j_forearm"),
    ))
    parts = (
        Part("base", Revolve(profile=((0.0, 0.0), (0.09, 0.0), (0.09, 0.02), (0.03, base_height), (0.0, base_height))),
             "paint", modifiers=(Bevel(width=0.003, segments=3),), smooth_angle=math.radians(35), parent_joint="j_base"),
        Part("arm", Cylinder(radius=0.012, height=p.arm_length), "paint",
             transform=Transform(translation=(0.0, base_height + p.arm_length / 2, 0.0)),
             modifiers=(Bevel(width=0.002, segments=2),), smooth_angle=math.radians(35), parent_joint="j_arm"),
        Part("elbow", Cylinder(radius=0.02, height=0.03), "steel",
             transform=Transform(translation=(0.0, elbow, 0.0), rotation=(math.pi / 2, 0.0, 0.0)),
             modifiers=(Bevel(width=0.002, segments=2),), smooth_angle=math.radians(35), parent_joint="j_forearm"),
        Part("forearm", Cylinder(radius=0.011, height=p.forearm_length), "paint",
             transform=Transform(translation=(0.0, elbow + p.forearm_length / 2, 0.0)),
             modifiers=(Bevel(width=0.002, segments=2),), smooth_angle=math.radians(35), parent_joint="j_forearm"),
        Part("shade", Cone(radius=0.09, height=0.12, top_radius=0.03), "paint",
             transform=Transform(translation=(0.0, head + 0.02, 0.05), rotation=(math.radians(-60), 0.0, 0.0)),
             modifiers=(Bevel(width=0.002, segments=2),), smooth_angle=math.radians(35), parent_joint="j_head"),
    )
    nod_down = Pose("nod_down", {
        "j_arm": JointTransform(rotation=(0.0, 0.0, math.radians(-25))),
        "j_forearm": JointTransform(rotation=(0.0, 0.0, math.radians(55))),
        "j_head": JointTransform(rotation=(0.0, 0.0, math.radians(-40))),
    })
    nod_up = Pose("nod_up", {
        "j_arm": JointTransform(rotation=(0.0, 0.0, math.radians(15))),
        "j_forearm": JointTransform(rotation=(0.0, 0.0, math.radians(-20))),
    })
    nod = Clip("nod", duration=2.0, keyframes=(
        Keyframe(0.0, None), Keyframe(0.8, "nod_down"), Keyframe(1.5, "nod_up"), Keyframe(2.0, None)))
    return Asset(name="Desk lamp", materials=(paint, steel), parts=parts, rig=rig, poses=(nod_down, nod_up), clips=(nod,))


asset = AssetGenerator(name="Desk lamp", parameters=LampParameters(), build=build, validate=validate, seed=2)
render = RenderSettings(resolution=640, views=("perspective", "side"), passes=("shaded",))
