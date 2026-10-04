"""Prepare a non-destructive, makeup-ready copy of RiggedWoman_v6.

Blender: -b --python character/prepare_makeup_base.py -- INPUT.blend OUTPUT.blend
"""

from __future__ import annotations

import sys
import math
from pathlib import Path

import bpy
from mathutils import Matrix, Vector
from mathutils.kdtree import KDTree


source, destination = (Path(value) for value in sys.argv[sys.argv.index("--") + 1:])
bpy.ops.wm.open_mainfile(filepath=str(source), load_ui=False, use_scripts=False)
body = bpy.data.objects["CC_Base_Body"]
body_keys = body.data.shape_keys.key_blocks
base = body_keys["Basis"]
flat = body_keys["PM_Bust_Flatten"]

# The supplied flatten key pulled the bust up to 9 cm behind the neighboring
# torso surface. Preserve its falloff, but limit the full reduction to about
# 3 cm so slider 0 describes a flat chest without a hollow in the rib cage.
for index in range(len(body.data.vertices)):
    flat.data[index].co = base.data[index].co + (flat.data[index].co - base.data[index].co) * 0.35

# The supplied file was saved with every PM editing key at 1.0. The neutral
# character and all new garment keys must be authored against Basis.
for key in body_keys:
    if key.name.startswith("PM_"):
        key.value = 0.0

tree = KDTree(len(body.data.vertices))
body_deltas = []
body_basis = body.matrix_world.to_3x3()
for vert in body.data.vertices:
    index = vert.index
    tree.insert(body.matrix_world @ base.data[index].co, index)
    body_deltas.append(body_basis @ (flat.data[index].co - base.data[index].co))
tree.balance()

garments = ["Bra", "Wardrobe_SportsBRA", "Wardrobe_BlouseA",
            "Wardrobe_Female_TankTop", "Wardrobe_Amber_CropTShirt",
            "Wardrobe_Streetwear_SportShirt", "Wardrobe_Medieval_Thin",
            "Wardrobe_Medieval_Thick", "Wardrobe_Lingerie_Set",
            "Wardrobe_FemaleOutfit", "Wardrobe_Megane_Uniform"]
for name in garments:
    obj = bpy.data.objects.get(name)
    if obj is None or obj.type != "MESH":
        continue
    if obj.data.shape_keys is not None:
        raise RuntimeError(f"Unexpected existing garment shape keys: {name}")
    obj.shape_key_add(name="Basis", from_mix=False)
    key = obj.shape_key_add(name="PM_Bust_Flatten", from_mix=False)
    inverse = obj.matrix_world.to_3x3().inverted()
    changed = 0
    for vert in obj.data.vertices:
        world = obj.matrix_world @ vert.co
        neighbors = tree.find_n(world, 4)
        if not neighbors or neighbors[0][2] > 0.14:
            continue
        weighted = Vector((0.0, 0.0, 0.0))
        total = 0.0
        for _, index, distance in neighbors:
            weight = 1.0 / max(distance, 0.003) ** 2
            weighted += body_deltas[index] * weight
            total += weight
        displacement = weighted / total
        # Loose cloth should move less than a close-fitting bra. Fade out at
        # distant cloth and leave straps away from the bust unchanged.
        proximity = max(0.0, min(1.0, (0.14 - neighbors[0][2]) / 0.11))
        if name != "Bra":
            proximity *= 0.9
        if displacement.length > 0.0001:
            key.data[vert.index].co = vert.co + inverse @ (displacement * proximity)
            changed += 1
    key.value = 0.0
    print("GARMENT_BUST_FIT", name, changed, len(obj.data.vertices), flush=True)

# The ponytail cap sat high above the forehead. Move only its authored mesh;
# keep the original base file and all rig weights intact.
hair = bpy.data.objects["Hair_Ponytail_Brown"]
hair.data = hair.data.copy()
world_shift = Matrix.Translation((0.0, -0.014, 0.0))
hair.data.transform(hair.matrix_world.inverted() @ world_shift @ hair.matrix_world)
hair.data.update()

# The imported headband's horizontal axis is 57 degrees from the body's X
# axis. Align that axis to the body's left-right direction, then center the
# hair on the head and keep the fringe clear of the eyes.
head_center = Vector((0.0, 0.0, 1.66))
# Lower the whole hairstyle by about 5 cm, then enlarge it around a low pivot
# so the crown regains its height and the wider silhouette wraps the head.
# A small front-only lift keeps the longer fringe clear of the eyes.
turn = (Matrix.Translation((-0.023, 0.020, -0.010)) @ Matrix.Translation(head_center)
        @ Matrix.Rotation(math.radians(-57), 4, "Z") @ Matrix.Translation(-head_center))
hair_scale_center = Vector((0.0, 0.0, 1.20))
seat_and_scale = (Matrix.Translation((0.0, 0.0, -0.040))
                  @ Matrix.Translation(hair_scale_center)
                  @ Matrix.Scale(1.06, 4)
                  @ Matrix.Translation(-hair_scale_center))
for index in range(5):
    obj = bpy.data.objects[f"Hair_Headband_Black_{index}"]
    obj.data = obj.data.copy()
    obj.data.transform(obj.matrix_world.inverted() @ seat_and_scale @ turn @ obj.matrix_world)
    inverse_basis = obj.matrix_world.to_3x3().inverted()
    for vertex in obj.data.vertices:
        world = obj.matrix_world @ vertex.co
        front = max(0.0, min(1.0, (0.020 - world.y) / 0.080))
        low = max(0.0, min(1.0, (1.730 - world.z) / 0.080))
        vertex.co += inverse_basis @ Vector((0.0, 0.0, 0.018 * front * low))
    obj.data.update()

# Thin, rigged dark scalp under the back strands fills the gaps in the source
# hairstyle without adding a visible band across the forehead.
normal_matrix = body.matrix_world.to_3x3().inverted().transposed()
positions = [body.matrix_world @ vertex.co for vertex in base.data]
normals = [(normal_matrix @ vertex.normal).normalized() for vertex in body.data.vertices]
back_faces = [polygon for polygon in body.data.polygons
              if all(positions[index].y > 0.020 and positions[index].z > 1.565
                     and abs(positions[index].x) < 0.077
                     for index in polygon.vertices)]
indices = sorted({index for polygon in back_faces for index in polygon.vertices})
mapping = {source_index: cap_index for cap_index, source_index in enumerate(indices)}
cap_mesh = bpy.data.meshes.new("Hair_Headband_Black_Cap_Mesh")
cap_mesh.from_pydata([positions[index] + normals[index] * 0.0025 for index in indices], [],
                     [[mapping[index] for index in polygon.vertices] for polygon in back_faces])
cap_mesh.update()
for polygon in cap_mesh.polygons:
    polygon.use_smooth = True
cap = bpy.data.objects.new("Hair_Headband_Black_Cap", cap_mesh)
bpy.context.scene.collection.objects.link(cap)
material = bpy.data.materials.new("Hair_Headband_Black_Cap_Material")
material.diffuse_color = (0.015, 0.015, 0.019, 1.0)
material.use_nodes = True
shader = next(node for node in material.node_tree.nodes if node.type == "BSDF_PRINCIPLED")
shader.inputs["Base Color"].default_value = material.diffuse_color
shader.inputs["Roughness"].default_value = 0.78
cap_mesh.materials.append(material)
group = cap.vertex_groups.new(name="CC_Base_Head")
group.add(list(range(len(indices))), 1.0, "REPLACE")
modifier = cap.modifiers.new("CharacterRig", "ARMATURE")
modifier.object = bpy.data.objects["CC3_Base_Plus"]
print("HEADBAND_CAP", len(indices), len(back_faces), flush=True)

bpy.context.scene.frame_set(1)
bpy.context.preferences.filepaths.save_version = 0
destination.parent.mkdir(parents=True, exist_ok=True)
bpy.ops.wm.save_as_mainfile(filepath=str(destination), compress=True)
print("MAKEUP_BASE_SAVED", destination, flush=True)
