"""Blender-side inventory of a candidate canonical base."""

import json
import sys
from pathlib import Path

import bpy


model, output = sys.argv[sys.argv.index("--") + 1:]
bpy.ops.object.select_all(action="SELECT")
bpy.ops.object.delete(use_global=False)
if model.lower().endswith(".blend"):
    bpy.ops.wm.open_mainfile(filepath=model, load_ui=False, use_scripts=False)
elif model.lower().endswith(".fbx"):
    bpy.ops.import_scene.fbx(filepath=model)
elif model.lower().endswith(".obj"):
    bpy.ops.wm.obj_import(filepath=model)
else:
    bpy.ops.import_scene.gltf(filepath=model)

objects = []
for obj in bpy.context.scene.objects:
    if obj.type not in ("MESH", "ARMATURE"):
        continue
    item = {"name": obj.name, "type": obj.type}
    if obj.type == "MESH":
        item["vertices"] = len(obj.data.vertices)
        item["shapeKeys"] = ([key.name for key in obj.data.shape_keys.key_blocks if key.name != "Basis"]
                             if obj.data.shape_keys else [])
        item["materials"] = [slot.material.name for slot in obj.material_slots if slot.material]
        item["skinned"] = any(mod.type == "ARMATURE" for mod in obj.modifiers)
        item["armatures"] = [mod.object.name for mod in obj.modifiers
                              if mod.type == "ARMATURE" and mod.object]
        item["vertexGroups"] = len(obj.vertex_groups)
        binding_modifiers = [mod for mod in obj.modifiers if mod.type == "ARMATURE"]
        deform_names = {bone.name for mod in binding_modifiers if mod.object
                        for bone in mod.object.data.bones if bone.use_deform}
        deform_groups = {group.index for group in obj.vertex_groups if group.name in deform_names}
        weighted = sum(any(group.group in deform_groups and group.weight > 1e-6
                           for group in vertex.groups) for vertex in obj.data.vertices)
        item["weightedVertices"] = weighted
        item["weightCoverage"] = weighted / len(obj.data.vertices) if obj.data.vertices else 0.
        item["bindingStatus"] = ("rigid_bone" if obj.parent_type == "BONE" and obj.parent
                                 else "unbound" if not binding_modifiers
                                 else "missing_armature" if not deform_names
                                 else "envelope_binding" if any(mod.show_viewport and mod.use_bone_envelopes
                                                                for mod in binding_modifiers)
                                 else "empty_weights" if weighted == 0
                                 else "disabled" if not any(mod.show_viewport and mod.use_vertex_groups
                                                           for mod in binding_modifiers)
                                 else "complete" if weighted == len(obj.data.vertices) else "partial")
        item["uvLayers"] = [layer.name for layer in obj.data.uv_layers]
    if obj.type == "ARMATURE":
        item["bones"] = [bone.name for bone in obj.data.bones]
    objects.append(item)

inventory = {"model": model, "objects": objects,
             "bindingIssues": [{"mesh": obj["name"], "status": obj["bindingStatus"],
                                 "weightedVertices": obj["weightedVertices"], "vertices": obj["vertices"]}
                                for obj in objects if obj["type"] == "MESH"
                                and obj["bindingStatus"] in ("missing_armature", "empty_weights", "disabled", "partial")],
             "shapeKeys": sorted({key for obj in objects for key in obj.get("shapeKeys", [])}),
             "bones": sorted({bone for obj in objects for bone in obj.get("bones", [])}),
             "materials": sorted({mat for obj in objects for mat in obj.get("materials", [])}),
             "images": [{"name": image.name, "path": bpy.path.abspath(image.filepath),
                         "size": list(image.size),
                         "exists": Path(bpy.path.abspath(image.filepath)).is_file(),
                         "packed": bool(image.packed_file)}
                        for image in bpy.data.images if image.source == "FILE"]}
Path(output).write_text(json.dumps(inventory, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
