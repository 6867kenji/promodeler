"""Blender helper: export one switchable GLB for immediate browser previews."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import bpy


model_path, manifest_path, output_path = (Path(value) for value in sys.argv[sys.argv.index("--") + 1:])
manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
output_path.parent.mkdir(parents=True, exist_ok=True)
bpy.ops.wm.open_mainfile(filepath=str(model_path), load_ui=False, use_scripts=False)

body = bpy.data.objects["CC_Base_Body"]
for obj in bpy.data.objects:
    if obj.type == "MESH" and obj.data.shape_keys:
        for key in list(obj.data.shape_keys.key_blocks)[::-1]:
            if key.name != "Basis" and not key.name.startswith("PM_"):
                obj.shape_key_remove(key)
        for key in obj.data.shape_keys.key_blocks:
            if key.name.startswith("PM_"):
                key.value = 0.0

mask_groups = sorted({mask["vertexGroup"]
                      for options in manifest.get("bodyMeshMasks", {}).values()
                      for masks in options.values() for mask in masks})
for group_name in mask_groups:
    group = body.vertex_groups.get(group_name)
    if group is None:
        raise RuntimeError(f"Missing body coverage group: {group_name}")
    name = "PM_Hide_" + group_name.removeprefix("PM_Cover_")
    if name in body.data.shape_keys.key_blocks:
        raise RuntimeError(f"Duplicate preview mask: {name}")
    key = body.shape_key_add(name=name, from_mix=False)
    covered = 0
    for vert in body.data.vertices:
        if any(item.group == group.index and item.weight > 0.5 for item in vert.groups):
            key.data[vert.index].co.x *= 0.68
            key.data[vert.index].co.y *= 0.63
            covered += 1
    key.value = 0.0
    print("PREVIEW_BODY_MASK", name, covered, flush=True)

for name in manifest.get("excludeObjects", []):
    obj = bpy.data.objects.get(name)
    if obj:
        bpy.data.objects.remove(obj, do_unlink=True)

objects = [obj for obj in bpy.context.scene.objects
           if obj.type in ("MESH", "ARMATURE") and not obj.name.startswith("WGT-")
           and bpy.context.view_layer.objects.get(obj.name) is not None]
images = set()
for obj in objects:
    obj.hide_set(False)
    obj.hide_viewport = False
    obj.hide_render = False
    if obj.type == "MESH":
        for slot in obj.material_slots:
            mat = slot.material
            if mat and mat.use_nodes:
                images.update(node.image for node in mat.node_tree.nodes
                              if node.type == "TEX_IMAGE" and node.image)
for image in images:
    width, height = image.size
    if max(width, height) > 1024:
        ratio = 1024 / max(width, height)
        image.scale(max(1, round(width * ratio)), max(1, round(height * ratio)))
        image.pack()

bpy.ops.object.select_all(action="DESELECT")
for obj in objects:
    obj.select_set(True)
bpy.ops.export_scene.gltf(filepath=str(output_path), export_format="GLB",
                          use_selection=True, export_apply=False, export_morph=True,
                          export_morph_normal=False, export_morph_tangent=False,
                          export_animations=False)
report = {"status": "ok", "objects": len(objects), "images": len(images),
          "bytes": output_path.stat().st_size,
          "masks": mask_groups}
output_path.with_suffix(".json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
print("LIVE_PREVIEW_EXPORTED", report, flush=True)
