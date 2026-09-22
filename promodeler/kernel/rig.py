"""Armature construction, automatic skin weights, rigid attachments, poses and clips."""

from __future__ import annotations

import math

import bpy
from mathutils import Euler, Matrix, Vector

from promodeler.core.diagnostics import ModelingError

from . import space
from .compile import CompiledScene

FPS = 24


def build_armature(scene: CompiledScene, rig_spec: dict) -> bpy.types.Object:
    armature = bpy.data.armatures.new(rig_spec["id"])
    obj = bpy.data.objects.new(rig_spec["id"], armature)
    bpy.context.scene.collection.objects.link(obj)
    obj.parent = scene.root
    obj.matrix_parent_inverse.identity()
    for other in bpy.context.scene.objects:
        other.select_set(False)
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.mode_set(mode="EDIT")
    try:
        bones = {}
        for joint in rig_spec["joints"]:
            bone = armature.edit_bones.new(joint["id"])
            bone.head = space.A2B @ Vector(joint["head"])
            bone.tail = space.A2B @ Vector(joint["tail"])
            bone.use_connect = False
            bones[joint["id"]] = bone
        for joint in rig_spec["joints"]:
            if joint["parent"]:
                bones[joint["id"]].parent = bones[joint["parent"]]
    finally:
        bpy.ops.object.mode_set(mode="OBJECT")
    for bone in obj.pose.bones:
        bone.rotation_mode = "XYZ"
    scene.armature = obj
    scene.joints = {j["id"]: j for j in rig_spec["joints"]}
    return obj


def _segment_distance(p: Vector, a: Vector, b: Vector) -> float:
    ab = b - a
    length2 = ab.length_squared
    if length2 <= 1e-12:
        return (p - a).length
    t = max(0.0, min(1.0, (p - a).dot(ab) / length2))
    return (p - (a + ab * t)).length


def skin_part(scene: CompiledScene, obj: bpy.types.Object, influences: int = 4) -> dict:
    """Distance-based weights: each vertex takes up to ``influences`` nearest bones, weighted by 1/d^4."""
    armature = scene.armature
    to_armature = armature.matrix_world.inverted() @ obj.matrix_world
    segments = []
    for bone in armature.data.bones:
        segments.append((bone.name, bone.head_local.copy(), bone.tail_local.copy()))
    groups = {name: obj.vertex_groups.new(name=name) for name, _, _ in segments}
    mesh = obj.data
    for vertex in mesh.vertices:
        p = to_armature @ vertex.co
        distances = sorted(((_segment_distance(p, a, b), name) for name, a, b in segments))[:influences]
        weights = [(name, 1.0 / (d ** 4 + 1e-12)) for d, name in distances]
        total = sum(w for _, w in weights)
        for name, w in weights:
            if w / total > 1e-4:
                groups[name].add([vertex.index], w / total, "REPLACE")
    saved = obj.matrix_world.copy()
    obj.parent = armature
    obj.parent_type = "OBJECT"
    obj.matrix_world = saved
    modifier = obj.modifiers.new("armature", "ARMATURE")
    modifier.object = armature
    modifier.use_vertex_groups = True
    return {"joints": len(segments), "influences": influences}


def attach_part(scene: CompiledScene, obj: bpy.types.Object, joint_id: str) -> None:
    armature = scene.armature
    if joint_id not in armature.data.bones:
        raise ModelingError("part.binding", f"Unknown joint {joint_id!r}.")
    saved = obj.matrix_world.copy()
    obj.parent = armature
    obj.parent_type = "BONE"
    obj.parent_bone = joint_id
    obj.matrix_world = saved


def bind_all(scene: CompiledScene, recipe: dict) -> dict | None:
    asset = recipe["asset"]
    if not asset.get("rig"):
        return None
    build_armature(scene, asset["rig"])
    scene.pose_specs = {p["id"]: p for p in asset.get("poses", [])}
    bindings = {}
    for part in asset["parts"]:
        objects = [scene.parts[part["id"]]] + [lod for lod in scene.lods.get(part["id"], [])]
        if part.get("skinned"):
            for obj in objects:
                bindings[obj.name] = skin_part(scene, obj)
        elif part.get("parent_joint"):
            for obj in objects:
                attach_part(scene, obj, part["parent_joint"])
    clips = [author_clip(scene, clip) for clip in asset.get("clips", [])]
    return {
        "id": asset["rig"]["id"], "joints": len(asset["rig"]["joints"]), "skinned": sorted(bindings),
        "poses": sorted(scene.pose_specs), "clips": clips,
    }


def apply_pose(scene: CompiledScene, pose_id: str | None) -> None:
    """Set every pose bone to the pose, or to rest when ``pose_id`` is None."""
    armature = scene.armature
    if armature is None:
        return
    # Parked clips on NLA tracks would overwrite the rest pose or a hand-set pose at
    # evaluation time; renders always run with them muted and the export re-enables them.
    if armature.animation_data is not None:
        armature.animation_data.use_nla = False
    spec = scene.pose_specs.get(pose_id, {"joints": {}}) if pose_id else {"joints": {}}
    for bone in armature.pose.bones:
        transform = spec["joints"].get(bone.name)
        if transform is None:
            bone.rotation_euler = Euler((0.0, 0.0, 0.0), "XYZ")
            bone.location = Vector((0.0, 0.0, 0.0))
        elif transform.get("space", "joint") == "world":
            # Authored axes -> Blender axes, then conjugate into the bone's rest frame.
            rest = bone.bone.matrix_local.to_3x3()
            authored = Euler(transform["rotation"], "XYZ").to_matrix()
            a2b = space.A2B.to_3x3()
            world = a2b @ authored @ a2b.inverted()
            local = rest.inverted() @ world @ rest
            bone.rotation_euler = local.to_euler("XYZ")
            bone.location = rest.inverted() @ (a2b @ Vector(transform["translation"]))
        else:
            bone.rotation_euler = Euler(transform["rotation"], "XYZ")
            bone.location = Vector(transform["translation"])
    bpy.context.view_layer.update()


def author_clip(scene: CompiledScene, clip: dict) -> dict:
    """Key the clip's poses into an action and park it on an NLA track named after the clip."""
    armature = scene.armature
    if armature.animation_data is None:
        armature.animation_data_create()
    preferences = bpy.context.preferences.edit
    saved_interpolation = preferences.keyframe_new_interpolation_type
    preferences.keyframe_new_interpolation_type = clip["interpolation"].upper()
    action = bpy.data.actions.new(clip["id"])
    armature.animation_data.action = action
    try:
        for key in clip["keyframes"]:
            frame = 1 + key["time"] * FPS
            bpy.context.scene.frame_set(int(round(frame)))
            apply_pose(scene, key["pose"])
            for bone in armature.pose.bones:
                bone.keyframe_insert("rotation_euler", frame=frame)
                bone.keyframe_insert("location", frame=frame)
    finally:
        preferences.keyframe_new_interpolation_type = saved_interpolation
        armature.animation_data.action = None
    track = armature.animation_data.nla_tracks.new()
    track.name = clip["id"]
    strip = track.strips.new(clip["id"], 1, action)
    strip.name = clip["id"]
    if clip["loop"]:
        strip.repeat = 1.0
    bpy.context.scene.frame_set(1)
    apply_pose(scene, None)
    end_frame = int(round(1 + clip["duration"] * FPS))
    bpy.context.scene.frame_end = max(bpy.context.scene.frame_end, end_frame)
    return {"id": clip["id"], "duration": clip["duration"], "frames": end_frame, "keyframes": len(clip["keyframes"]),
            "loop": clip["loop"]}
