"""M5 example: a skinned tapering tube with four joints and a "wave" clip.

Run:  python -m promodeler build assets/tentacle.py --pose curl
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from promodeler.core import (
    Asset, AssetGenerator, Clip, GenerationInput, Joint, JointTransform, Keyframe, ModelingError, Part, Pose,
    Profile, RenderSettings, Rig, Sweep, curves, presets, srgb,
)


@dataclass(frozen=True)
class TentacleParameters:
    length: float = 0.5
    radius: float = 0.04
    segments: int = 4


def validate(p: TentacleParameters) -> None:
    if not 0.1 <= p.length <= 3.0 or not 0.01 <= p.radius <= 0.5:
        raise ModelingError("tentacle.size", "length must be 10 cm...3 m and radius 1...50 cm.")
    if not 2 <= p.segments <= 12:
        raise ModelingError("tentacle.segments", "segments must be 2...12.")


def build(input: GenerationInput) -> Asset:
    p: TentacleParameters = input.parameters
    leather = presets.worn_leather("skin", color=srgb(0.4, 0.28, 0.22), seed=input.seed, wear=0.4, edge_radius=0.02)
    steps = 24
    path = tuple((0.0, p.length * i / steps, 0.0) for i in range(steps + 1))
    scales = tuple(1.0 - 0.85 * (i / steps) ** 1.3 for i in range(steps + 1))
    body = Part(
        id="body",
        shape=Sweep(profile=Profile(curves.circle(p.radius, 24)), path=path, scales=scales, capped=True),
        material="skin",
        smooth_angle=math.radians(60),
        skinned=True,
    )
    joints = []
    for i in range(p.segments):
        y0 = p.length * i / p.segments
        y1 = p.length * (i + 1) / p.segments
        joints.append(Joint(f"j{i}", head=(0.0, y0, 0.0), tail=(0.0, y1, 0.0), parent=None if i == 0 else f"j{i - 1}"))
    rig = Rig("tentacle", joints=tuple(joints))
    bend = math.radians(70) / p.segments
    curl = Pose("curl", {j.id: JointTransform(rotation=(bend, 0.0, 0.0)) for j in joints[1:]})
    sway = Pose("sway", {j.id: JointTransform(rotation=(0.0, 0.0, -bend * 0.7)) for j in joints[1:]})
    wave = Clip("wave", duration=3.0, keyframes=(
        Keyframe(0.0, None), Keyframe(1.0, "curl"), Keyframe(2.0, "sway"), Keyframe(3.0, None)))
    return Asset(name="Tentacle", materials=(leather,), parts=(body,), rig=rig, poses=(curl, sway), clips=(wave,))


asset = AssetGenerator(name="Tentacle", parameters=TentacleParameters(), build=build, validate=validate, seed=4)
render = RenderSettings(resolution=640, views=("perspective", "front"), passes=("shaded", "wireframe"))
