from __future__ import annotations

import os

import bpy

from promodeler.core.diagnostics import ModelingError

from .compile import CompiledScene


def _select_export_objects(scene: CompiledScene) -> None:
    if scene.armature is not None and scene.armature.animation_data is not None:
        scene.armature.animation_data.use_nla = True
    names = {scene.root.name, *scene.parts}
    names.update(obj.name for objects in scene.lods.values() for obj in objects)
    if scene.armature is not None:
        names.add(scene.armature.name)
    for obj in bpy.context.scene.objects:
        obj.select_set(obj.name in names)


def export_gltf(scene: CompiledScene, path: str, has_clips: bool = False) -> dict:
    """Write a binary glTF of the frozen parts with authored (Y up) node transforms, skins and clips."""
    if not scene.frozen:
        raise ModelingError("export.notFrozen", "Freeze geometry before exporting so mesh names and results match the report.")
    _select_export_objects(scene)
    options = dict(
        filepath=path,
        export_format="GLB",
        use_selection=True,
        export_apply=False,
        export_yup=True,
        export_cameras=False,
        export_lights=False,
        export_materials="EXPORT",
        export_extras=True,
        export_skins=scene.armature is not None,
        export_animations=has_clips,
    )
    if has_clips:
        options["export_animation_mode"] = "NLA_TRACKS"
        options["export_nla_strips"] = True
    if scene.armature is not None:
        options["export_rest_position_armature"] = True
        options["export_def_bones"] = False
    bpy.ops.export_scene.gltf(**options)
    written = os.path.isfile(path) and os.path.getsize(path) > 0
    return {"path": path, "written": written, "bytes": os.path.getsize(path) if written else 0}


def export_usdz(scene: CompiledScene, path: str, has_clips: bool = False) -> dict:
    _select_export_objects(scene)
    bpy.ops.wm.usd_export(
        filepath=path,
        selected_objects_only=True,
        export_animation=has_clips,
        export_materials=True,
        export_armatures=scene.armature is not None,
        generate_preview_surface=True,
    )
    written = os.path.isfile(path) and os.path.getsize(path) > 0
    return {"path": path, "written": written, "bytes": os.path.getsize(path) if written else 0}
