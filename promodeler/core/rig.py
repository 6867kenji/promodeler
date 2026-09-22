"""Rigs, poses and animation clips.

A rig is a tree of joints defined by head and tail points in authoring
space (Y up). Parts bind to it either by automatic distance weights
(``Part(skin=...)``) or rigidly to one joint (``Part(parent_joint=...)``).
Poses give per-joint transforms in each joint's local frame, where local Y
runs from head to tail; clips key poses over time. The runtime animation
graph belongs to the consuming engine; the export carries the clips.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .diagnostics import ModelingError, finite_vector, is_finite

INTERPOLATIONS = ("linear", "bezier", "constant")


@dataclass(frozen=True)
class Joint:
    id: str
    head: tuple[float, float, float]
    tail: tuple[float, float, float]
    parent: str | None = None

    def validate(self, label: str) -> None:
        if not isinstance(self.id, str) or not self.id or any(c.isspace() for c in self.id):
            raise ModelingError("joint.id", f"{label}.id must be a nonempty string without whitespace.")
        head = finite_vector(self.head, 3, "joint.head", f"{label}.head")
        tail = finite_vector(self.tail, 3, "joint.tail", f"{label}.tail")
        if sum((a - b) ** 2 for a, b in zip(head, tail)) < 1e-12:
            raise ModelingError("joint.length", f"{label} head and tail coincide.")

    def to_recipe(self) -> dict:
        return {"id": self.id, "head": [float(c) for c in self.head], "tail": [float(c) for c in self.tail], "parent": self.parent}


@dataclass(frozen=True)
class Rig:
    id: str
    joints: tuple[Joint, ...]

    def validate(self) -> None:
        label = f"rig[{self.id!r}]"
        if not isinstance(self.id, str) or not self.id:
            raise ModelingError("rig.id", f"{label}.id must be a nonempty string.")
        if not self.joints:
            raise ModelingError("rig.joints", f"{label} needs at least one joint.")
        ids: set[str] = set()
        for index, joint in enumerate(self.joints):
            joint.validate(f"{label}.joints[{index}]")
            if joint.id in ids:
                raise ModelingError("joint.duplicateID", f"Joint id {joint.id!r} is defined twice.")
            ids.add(joint.id)
        parents = {j.id: j.parent for j in self.joints}
        for joint in self.joints:
            if joint.parent is not None and joint.parent not in ids:
                raise ModelingError("joint.parent", f"Joint {joint.id!r} references unknown parent {joint.parent!r}.")
            seen = {joint.id}
            current = joint.parent
            while current is not None:
                if current in seen:
                    raise ModelingError("joint.parentCycle", f"Joint {joint.id!r} has a parent cycle.")
                seen.add(current)
                current = parents[current]

    def joint_ids(self) -> set[str]:
        return {j.id for j in self.joints}

    def to_recipe(self) -> dict:
        return {"id": self.id, "joints": [j.to_recipe() for j in self.joints]}


POSE_SPACES = ("joint", "world")


@dataclass(frozen=True)
class JointTransform:
    """Rotation (XYZ Euler, radians) and translation (meters) of one joint.

    ``space="joint"`` uses the joint's local rest frame (Y from head to
    tail), which depends on the bone roll. ``space="world"`` uses the
    authoring axes (Y up, Z toward the viewer) as if every parent were at
    rest, which is the natural way to write verification poses: raising an
    arm sideways is a rotation about world Z.
    """

    rotation: tuple[float, float, float] = (0.0, 0.0, 0.0)
    translation: tuple[float, float, float] = (0.0, 0.0, 0.0)
    space: str = "joint"

    def validate(self, label: str) -> None:
        finite_vector(self.rotation, 3, "pose.rotation", f"{label}.rotation")
        finite_vector(self.translation, 3, "pose.translation", f"{label}.translation")
        if self.space not in POSE_SPACES:
            raise ModelingError("pose.space", f"{label}.space must be one of {POSE_SPACES}.")

    def to_recipe(self) -> dict:
        return {"rotation": [float(c) for c in self.rotation], "translation": [float(c) for c in self.translation],
                "space": self.space}


@dataclass(frozen=True)
class Pose:
    """Joint transforms plus shape-key weights (``shapes``: name -> 0...1, keys from a ``MeshFile``)."""

    id: str
    joints: dict[str, JointTransform]
    shapes: dict[str, float] = field(default_factory=dict)

    def validate(self, label: str, joint_ids: set[str]) -> None:
        if not isinstance(self.id, str) or not self.id:
            raise ModelingError("pose.id", f"{label}.id must be a nonempty string.")
        if not self.joints and not self.shapes:
            raise ModelingError("pose.joints", f"{label} sets no joints or shapes.")
        for joint_id, transform in self.joints.items():
            if joint_id not in joint_ids:
                raise ModelingError("pose.joint", f"{label} references unknown joint {joint_id!r}.")
            transform.validate(f"{label}.joints[{joint_id!r}]")
        for name, value in self.shapes.items():
            if not isinstance(name, str) or not name:
                raise ModelingError("pose.shape", f"{label}.shapes keys must be shape key names.")
            if not is_finite(value) or not 0.0 <= float(value) <= 1.0:
                raise ModelingError("pose.shape", f"{label}.shapes[{name!r}] must be in 0...1.")

    def to_recipe(self) -> dict:
        return {"id": self.id, "joints": {k: v.to_recipe() for k, v in sorted(self.joints.items())},
                "shapes": {k: float(v) for k, v in sorted(self.shapes.items())}}


@dataclass(frozen=True)
class Keyframe:
    time: float
    pose: str | None  # None keys the rest pose


@dataclass(frozen=True)
class Clip:
    """Keyed poses over ``duration`` seconds. Unkeyed joints hold their rest transform."""

    id: str
    duration: float
    keyframes: tuple[Keyframe, ...]
    loop: bool = True
    interpolation: str = "bezier"

    def validate(self, label: str, pose_ids: set[str]) -> None:
        if not isinstance(self.id, str) or not self.id:
            raise ModelingError("clip.id", f"{label}.id must be a nonempty string.")
        if not is_finite(self.duration) or self.duration <= 0.0 or self.duration > 3600.0:
            raise ModelingError("clip.duration", f"{label}.duration must be in (0, 3600] seconds.")
        if len(self.keyframes) < 2:
            raise ModelingError("clip.keyframes", f"{label} needs at least 2 keyframes.")
        last = -1.0
        for index, key in enumerate(self.keyframes):
            if not is_finite(key.time) or key.time < 0.0 or key.time > self.duration or key.time <= last:
                raise ModelingError("clip.keyframes", f"{label}.keyframes[{index}] times must ascend within 0...duration.")
            last = key.time
            if key.pose is not None and key.pose not in pose_ids:
                raise ModelingError("clip.pose", f"{label}.keyframes[{index}] references unknown pose {key.pose!r}.")
        if self.interpolation not in INTERPOLATIONS:
            raise ModelingError("clip.interpolation", f"{label}.interpolation must be one of {INTERPOLATIONS}.")

    def to_recipe(self) -> dict:
        return {
            "id": self.id, "duration": float(self.duration), "loop": bool(self.loop), "interpolation": self.interpolation,
            "keyframes": [{"time": float(k.time), "pose": k.pose} for k in self.keyframes],
        }
