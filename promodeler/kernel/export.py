from __future__ import annotations

import os

import bpy

from promodeler.core.diagnostics import ModelingError

from .compile import CompiledScene


def export_gltf(scene: CompiledScene, path: str) -> dict:
    """Write a binary glTF of the frozen parts with authored (Y up) node transforms."""
    if not scene.frozen:
        raise ModelingError("export.notFrozen", "Freeze geometry before exporting so mesh names and results match the report.")
    for obj in bpy.context.scene.objects:
        obj.select_set(obj == scene.root or obj.name in scene.parts)
    bpy.ops.export_scene.gltf(
        filepath=path,
        export_format="GLB",
        use_selection=True,
        export_apply=False,
        export_yup=True,
        export_cameras=False,
        export_lights=False,
        export_animations=False,
        export_materials="EXPORT",
    )
    written = os.path.isfile(path) and os.path.getsize(path) > 0
    return {"path": path, "written": written, "bytes": os.path.getsize(path) if written else 0}
