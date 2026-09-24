"""Surface finishing after geometry is frozen: UVs and texture baking for procedural materials."""

from __future__ import annotations

import os

import bpy

from . import materials, tiled, uv
from .compile import CompiledScene


def finish(scene: CompiledScene, recipe: dict, out_dir: str, reuse_textures: bool = False) -> None:
    """Unwrap and bake every part with a procedural material.

    With ``reuse_textures`` the previously baked PNGs in ``out_dir/textures``
    are loaded instead of baked when the complete set is present; the host
    only asks for this when the asset recipe is unchanged.
    """
    quality = (recipe.get("input") or {}).get("quality") or {"texture_resolution": 1024, "bake_samples": 32}
    material_specs = {m["id"]: m for m in recipe["asset"]["materials"]}
    part_specs = {p["id"]: p for p in recipe["asset"]["parts"]}
    textures_dir = os.path.join(out_dir, "textures")
    tile_specs = (recipe["asset"].get("extras") or {}).get("tiled_materials", {})
    tiled_materials = {mid: tiled.build(material_specs[mid], tile, textures_dir)
                       for mid, tile in tile_specs.items()}
    previous_engine = bpy.context.scene.render.engine
    # Scattered and fur geometry is dense decoration; keep it out of the bake
    # ray tracing so probes on the underlying parts stay fast.
    decorations = [scene.parts[pid] for pid in scene.generated]
    for obj in decorations:
        obj.hide_render = True
    for part_id, obj in scene.parts.items():
        part_spec = part_specs[part_id]
        material_id = part_spec["material"]
        if material_id in tiled_materials:
            tile = tile_specs[material_id]
            tiled.project(obj, tile["scale_m"])
            scene.uv_stats[part_id] = uv.uv_statistics(obj.data, tile.get("resolution", 256))
            material, textures = tiled_materials[material_id]
            obj.data.materials[0] = material
            scene.textures[part_id] = textures
            continue
        proc = scene.procedural.get(material_id)
        if proc is None:
            continue
        part_quality = dict(quality)
        part_quality["texture_resolution"] = part_spec.get("texture_resolution") or quality["texture_resolution"]
        uv.unwrap(obj)
        scene.uv_stats[part_id] = uv.uv_statistics(obj.data, part_quality["texture_resolution"])
        spec = material_specs[material_id]
        textures = None
        if reuse_textures:
            textures = materials.load_textures(spec, proc, part_quality, textures_dir, part_id)
        if textures is None:
            textures = materials.bake_part(obj, spec, proc, part_quality, textures_dir, part_id)
        scene.textures[part_id] = textures
        obj.data.materials[0] = materials.build_baked_material(spec, textures, part_id)
    for obj in decorations:
        obj.hide_render = False
    bpy.context.scene.render.engine = previous_engine
