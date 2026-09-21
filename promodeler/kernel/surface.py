"""Surface finishing after geometry is frozen: UVs and texture baking for procedural materials."""

from __future__ import annotations

import os

import bpy

from . import materials, uv
from .compile import CompiledScene


def finish(scene: CompiledScene, recipe: dict, out_dir: str) -> None:
    quality = (recipe.get("input") or {}).get("quality") or {"texture_resolution": 1024, "bake_samples": 32}
    material_specs = {m["id"]: m for m in recipe["asset"]["materials"]}
    part_specs = {p["id"]: p for p in recipe["asset"]["parts"]}
    textures_dir = os.path.join(out_dir, "textures")
    previous_engine = bpy.context.scene.render.engine
    for part_id, obj in scene.parts.items():
        material_id = part_specs[part_id]["material"]
        proc = scene.procedural.get(material_id)
        if proc is None:
            continue
        uv.unwrap(obj)
        scene.uv_stats[part_id] = uv.uv_statistics(obj.data, quality["texture_resolution"])
        spec = material_specs[material_id]
        textures = materials.bake_part(obj, spec, proc, quality, textures_dir, part_id)
        scene.textures[part_id] = textures
        obj.data.materials[0] = materials.build_baked_material(spec, textures, part_id)
    bpy.context.scene.render.engine = previous_engine
