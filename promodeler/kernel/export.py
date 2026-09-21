from __future__ import annotations

import os

import bpy

from .compile import CompiledScene


def export_gltf(scene: CompiledScene, path: str) -> dict:
    """Write a binary glTF with modifiers applied and authored (Y up) node transforms."""
    for obj in bpy.context.scene.objects:
        obj.select_set(obj == scene.root or obj.name in scene.parts)
    bpy.ops.export_scene.gltf(
        filepath=path,
        export_format="GLB",
        use_selection=True,
        export_apply=True,
        export_yup=True,
        export_cameras=False,
        export_lights=False,
        export_animations=False,
        export_materials="EXPORT",
    )
    written = os.path.isfile(path) and os.path.getsize(path) > 0
    return {"path": path, "written": written, "bytes": os.path.getsize(path) if written else 0}
