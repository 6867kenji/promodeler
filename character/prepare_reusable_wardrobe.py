"""Reuse separated CC garments on the common base using bind-bone transforms.

Blender: -- BASE.blend AMBER.fbx MEGANE.fbx OUTPUT.blend
Source files remain untouched. Write a descriptor beside the prepared Blend.
"""

import json
import sys
from pathlib import Path

import bpy
import bmesh
import numpy as np
from mathutils import Matrix


base, amber, megane, output = map(Path, sys.argv[sys.argv.index("--") + 1:])
bpy.ops.wm.open_mainfile(filepath=str(base))
target_rig = bpy.data.objects["CC3_Base_Plus"]
body = bpy.data.objects["CC_Base_Body"]
descriptor = {"modules": {}, "bodyMasks": {}, "bodyMeshMasks": {}, "items": []}


def add_module(slot, asset_id, name, sources, source_file, coverage=None, remove=None):
    path = "wardrobe." + slot
    descriptor["modules"].setdefault(path, {})[asset_id] = [name]
    if coverage:
        descriptor["bodyMeshMasks"].setdefault(path, {})[asset_id] = [
            {"object": body.name, "vertexGroup": coverage}]
    if remove:
        descriptor["bodyMasks"].setdefault(path, {})[asset_id] = remove
    descriptor["items"].append({"id": asset_id, "slot": slot, "objects": [name],
                                "sourceObjects": sources, "sourceModel": str(source_file),
                                "compatibleBases": ["RiggedWoman_v5"], "rig": "CC3_Base_Plus",
                                "fit": "bind_bone_transfer", "materials": "source_textures_preserved"})


def split_materials(source, name, materials):
    mesh = source.data.copy()
    edit = bmesh.new()
    edit.from_mesh(mesh)
    bmesh.ops.delete(edit, geom=[f for f in edit.faces if f.material_index not in materials], context="FACES")
    loose = [v for v in edit.verts if not v.link_faces]
    if loose:
        bmesh.ops.delete(edit, geom=loose, context="VERTS")
    edit.to_mesh(mesh)
    edit.free()
    obj = source.copy()
    obj.data = mesh
    obj.name = name
    bpy.context.scene.collection.objects.link(obj)
    return obj


full_outfit = bpy.data.objects["Wardrobe_FemaleOutfit"]
pants_materials = {0, 3, 4, 5, 6, 7, 8, 9, 10, 16, 17, *range(22, 38)}
for slot, asset_id, name, materials, coverage, remove in (
    ("bottom", "female_cargo_pants", "Wardrobe_Female_CargoPants", pants_materials, "PM_Cover_Lower", ["Underwear_Bottoms"]),
    ("top", "female_tank_top", "Wardrobe_Female_TankTop", {1}, "PM_Cover_CropTop", ["Bra"]),
    ("outer", "female_jacket", "Wardrobe_Female_Jacket", set(range(42)) - pants_materials - {1}, "PM_Cover_LongSleeves", None),
):
    obj = split_materials(full_outfit, name, materials)
    add_module(slot, asset_id, name, [full_outfit.name], base, coverage, remove)


def remap_garment(obj, source_rig, name):
    source_matrix = np.asarray(obj.matrix_world)
    positions = np.empty(len(obj.data.vertices) * 3, dtype=np.float64)
    obj.data.vertices.foreach_get("co", positions)
    world = positions.reshape(-1, 3) @ source_matrix[:3, :3].T + source_matrix[:3, 3]
    weights = {}
    for vertex in obj.data.vertices:
        for assignment in vertex.groups:
            bone_name = obj.vertex_groups[assignment.group].name
            if assignment.weight > 1e-6:
                if bone_name not in source_rig.data.bones or bone_name not in target_rig.data.bones:
                    raise ValueError(f"Incompatible garment bone {bone_name} on {obj.name}")
                weights.setdefault(bone_name, []).append((vertex.index, assignment.weight))
    fitted = np.zeros_like(world)
    sums = np.zeros(len(world))
    for bone_name, assignments in weights.items():
        source_rest = source_rig.matrix_world @ source_rig.data.bones[bone_name].matrix_local
        target_rest = target_rig.matrix_world @ target_rig.data.bones[bone_name].matrix_local
        transform = np.asarray(target_rest @ source_rest.inverted())
        indices = np.array([a[0] for a in assignments], dtype=np.int32)
        values = np.array([a[1] for a in assignments])
        moved = world[indices] @ transform[:3, :3].T + transform[:3, 3]
        fitted[indices] += moved * values[:, None]
        sums[indices] += values
    if np.any(sums < .001):
        raise ValueError(f"Unweighted vertices on {obj.name}")
    fitted /= sums[:, None]
    obj.parent = None
    obj.matrix_world = Matrix.Identity(4)
    obj.data.vertices.foreach_set("co", fitted.ravel())
    for modifier in list(obj.modifiers):
        if modifier.type == "ARMATURE":
            obj.modifiers.remove(modifier)
    modifier = obj.modifiers.new("CommonCharacterRig", "ARMATURE")
    modifier.object = target_rig
    obj.name = name
    obj.data.update()
    print("TRANSFERRED_GARMENT", name, len(world), "weighted", int(np.sum(sums > .001)))


for source_file, items in (
    (amber, (
        ("Crop_T_Shirt", "Wardrobe_Amber_CropTShirt", "top", "amber_crop_tshirt", "PM_Cover_CropTop", ["Bra"]),
        ("Jeans", "Wardrobe_Amber_Jeans", "bottom", "amber_jeans", "PM_Cover_Lower", ["Underwear_Bottoms"]),
        ("Boots", "Wardrobe_Amber_Boots", "shoes", "amber_boots", "PM_Cover_Feet", None),
        ("Punk_Leather_Jacket", "Wardrobe_Amber_LeatherJacket", "outer", "amber_leather_jacket", "PM_Cover_LongSleeves", None),
    )),
    (megane, (("Pants_Shirt_Aesthetician", "Wardrobe_Megane_Uniform", "dress", "megane_uniform", "PM_Cover_Uniform", ["Bra", "Underwear_Bottoms"]),)),
):
    before = set(bpy.data.objects)
    bpy.ops.import_scene.fbx(filepath=str(source_file))
    imported = set(bpy.data.objects) - before
    source_rig = next(obj for obj in imported if obj.type == "ARMATURE")
    for obj in imported:
        obj.animation_data_clear()
        if obj.type == "ARMATURE":
            for bone in obj.pose.bones:
                bone.matrix_basis = Matrix.Identity(4)
    bpy.context.view_layer.update()
    keep = set()
    for original, name, slot, asset_id, coverage, remove in items:
        obj = next(obj for obj in imported if obj.name == original)
        remap_garment(obj, source_rig, name)
        keep.add(obj)
        add_module(slot, asset_id, name, [original], source_file, coverage, remove)
    for obj in imported - keep:
        data = obj.data
        kind = obj.type
        bpy.data.objects.remove(obj, do_unlink=True)
        if kind == "MESH" and data.users == 0:
            bpy.data.meshes.remove(data)


def coverage(name, test, materials=None):
    group = body.vertex_groups.get(name) or body.vertex_groups.new(name=name)
    allowed = None if materials is None else {i for p in body.data.polygons if p.material_index in materials for i in p.vertices}
    group.add([v.index for v in body.data.vertices if (allowed is None or v.index in allowed)
               and test(body.matrix_world @ v.co)], 1, "REPLACE")


coverage("PM_Cover_Lower", lambda p: .08 < p.z < .99)
coverage("PM_Cover_Feet", lambda p: p.z < .18)
coverage("PM_Cover_CropTop", lambda p: abs(p.x) < .19 and 1.20 < p.z < 1.46)
coverage("PM_Cover_LongSleeves", lambda p: .17 < abs(p.x) < .5 and p.z > 1.18)
coverage("PM_Cover_Uniform", lambda p: .1 < p.z < 1.46, {1, 3})
bpy.context.preferences.filepaths.save_version = 0
output.parent.mkdir(parents=True, exist_ok=True)
bpy.ops.wm.save_as_mainfile(filepath=str(output))
output.with_suffix(".modules.json").write_text(json.dumps(descriptor, ensure_ascii=False, indent=2), encoding="utf-8")
print("PREPARED_REUSABLE_WARDROBE", output)
