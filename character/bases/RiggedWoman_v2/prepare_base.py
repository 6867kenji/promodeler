"""Prepare the supplied CC3 woman FBX as an editable canonical base.

The source FBX is left untouched. This script adds restrained face-proportion
shape keys and a separate, head-weighted blue-silver hair module.
Run with Blender: blender -b --factory-startup --python prepare_base.py -- SOURCE.fbx OUTPUT.blend
"""

import math
import sys
from pathlib import Path

import bpy
from mathutils import Matrix, Vector


source, destination = sys.argv[sys.argv.index("--") + 1:]
destination = Path(destination).resolve()
destination.parent.mkdir(parents=True, exist_ok=True)

bpy.ops.object.select_all(action="SELECT")
bpy.ops.object.delete(use_global=False)
bpy.ops.import_scene.fbx(filepath=source)
for obj in bpy.data.objects:
    obj.animation_data_clear()
    if obj.type == "ARMATURE":
        for bone in obj.pose.bones:
            bone.matrix_basis = Matrix.Identity(4)
    elif obj.type == "MESH" and obj.data.shape_keys:
        obj.data.shape_keys.animation_data_clear()
        for key in obj.data.shape_keys.key_blocks:
            if key.name != "Basis":
                key.value = 0.0
bpy.context.view_layer.update()

body = bpy.data.objects["CC_Base_Body"]
armature = bpy.data.objects["CC3_Base_Plus"]
eye_bones = [armature.data.bones[f"CC_Base_{side}_Eye"] for side in ("L", "R")]
eyes = [armature.matrix_world @ bone.head_local for bone in eye_bones]
eye_height = (eyes[0].z + eyes[1].z) / 2


def bell(value, center, radius):
    return math.exp(-0.5 * ((value - center) / radius) ** 2)


def face_delta(name, co):
    x, y, z = co
    forward = max(0.0, min(1.0, (0.07 - y) / 0.12))
    cheek = bell(z, eye_height - 0.045, 0.055) * bell(y, -0.04, 0.06) * forward
    jaw = bell(z, eye_height - 0.078, 0.045) * bell(y, -0.025, 0.07) * forward
    nose = bell(x, 0, 0.023) * bell(z, eye_height - 0.035, 0.038) * bell(y, -0.086, 0.035)
    eye = max(bell(x, center.x, 0.029) * bell(z, center.z, 0.018)
              * bell(y, center.y - 0.008, 0.032) for center in eyes)
    center = min(eyes, key=lambda candidate: abs(x - candidate.x))
    if name == "PM_Face_Round":
        return Vector((x * 0.095 * cheek, -0.002 * cheek, 0))
    if name == "PM_Face_Narrow":
        return Vector((-x * 0.095 * cheek, 0, 0))
    if name == "PM_Jaw_Wide":
        return Vector((x * 0.115 * jaw, 0, 0))
    if name == "PM_Jaw_Narrow":
        return Vector((-x * 0.115 * jaw, 0, 0))
    if name == "PM_Cheek_Full":
        return Vector((x * 0.075 * cheek, -0.003 * cheek, 0))
    if name == "PM_Cheek_Slim":
        return Vector((-x * 0.075 * cheek, 0.002 * cheek, 0))
    if name == "PM_Nose_Large":
        return Vector((x * 0.11 * nose, -0.004 * nose, 0))
    if name == "PM_Nose_Small":
        return Vector((-x * 0.11 * nose, 0.004 * nose, 0))
    if name == "PM_Eye_Large":
        return Vector(((x - center.x) * 0.105 * eye, 0, (z - center.z) * 0.105 * eye))
    if name == "PM_Eye_Small":
        return Vector((-(x - center.x) * 0.105 * eye, 0, -(z - center.z) * 0.105 * eye))
    return Vector((0, 0, 0))


def add_face_key(obj, name, whole_eye=False):
    if obj.data.shape_keys:
        basis = obj.data.shape_keys.key_blocks[0]
    else:
        basis = obj.shape_key_add(name="Basis")
    key = obj.shape_key_add(name=name)
    to_local = obj.matrix_world.inverted().to_3x3()
    for index, point in enumerate(basis.data):
        world = obj.matrix_world @ point.co
        if whole_eye:
            center = min(eyes, key=lambda candidate: abs(world.x - candidate.x))
            sign = 1 if name == "PM_Eye_Large" else -1
            delta = Vector(((world.x - center.x) * sign * 0.065,
                            0, (world.z - center.z) * sign * 0.065))
        else:
            delta = face_delta(name, world)
        key.data[index].co = point.co + to_local @ delta


face_keys = ("PM_Face_Round", "PM_Face_Narrow", "PM_Jaw_Wide", "PM_Jaw_Narrow",
             "PM_Cheek_Full", "PM_Cheek_Slim", "PM_Nose_Large", "PM_Nose_Small",
             "PM_Eye_Large", "PM_Eye_Small")
for name in face_keys:
    add_face_key(body, name)
for object_name in ("CC_Game_Eye", "CC_Base_EyeOcclusion", "CC_Base_TearLine"):
    for name in ("PM_Eye_Large", "PM_Eye_Small"):
        add_face_key(bpy.data.objects[object_name], name, whole_eye=True)


def hair_texture(name, base):
    image = bpy.data.images.new(name, width=256, height=512)
    pixels = []
    for row in range(512):
        v = row / 511
        for column in range(256):
            u = column / 255
            fiber = (math.sin(u * 147) * 0.045 + math.sin(u * 331 + v * 9) * 0.028
                     + math.sin(u * 701 - v * 18) * 0.012)
            root = -0.11 * (1 - min(1, v * 5))
            tip = -0.035 * max(0, (v - 0.82) / 0.18)
            value = fiber + root + tip
            pixels.extend((max(0, min(1, base[0] + value)),
                           max(0, min(1, base[1] + value)),
                           max(0, min(1, base[2] + value)), 1.0))
    image.pixels.foreach_set(pixels)
    image.filepath_raw = str(destination.parent / f"{name}.png")
    image.file_format = "PNG"
    image.save()
    image.pack()
    return image


def hair_material(name, base):
    material = bpy.data.materials.new(name)
    material.use_nodes = True
    bsdf = next(node for node in material.node_tree.nodes if node.type == "BSDF_PRINCIPLED")
    bsdf.inputs["Roughness"].default_value = 0.34
    bsdf.inputs["Metallic"].default_value = 0.04
    texture = material.node_tree.nodes.new("ShaderNodeTexImage")
    texture.image = hair_texture(name, base)
    material.node_tree.links.new(texture.outputs["Color"], bsdf.inputs["Base Color"])
    return material


materials = [hair_material("Hair_SilverBlue_Base", (0.62, 0.73, 0.90)),
             hair_material("Hair_SilverBlue_Shadow", (0.18, 0.30, 0.55)),
             hair_material("Hair_SilverBlue_Glint", (0.82, 0.87, 0.98))]
vertices = []
faces = []
face_materials = []
face_uvs = []


def add_face(indices, material, uvs):
    faces.append(indices)
    face_materials.append(material)
    face_uvs.append(uvs)


# Sculpted scalp shell; long locks and bangs remain separate islands inside one module.
segments = 40
rings = 15
for ring in range(rings):
    theta = 0.035 + 2.16 * ring / (rings - 1)
    for segment in range(segments):
        angle = 2 * math.pi * segment / segments
        radial = math.sin(theta) * (1 + 0.17 * (theta / 2.2) ** 4)
        x = 0.093 * radial * math.cos(angle)
        y = 0.013 + 0.087 * radial * math.sin(angle)
        z = 1.682 + 0.078 * math.cos(theta)
        vertices.append((x, y, z))
for ring in range(rings - 1):
    for segment in range(segments):
        next_segment = (segment + 1) % segments
        a = ring * segments + segment
        b = ring * segments + next_segment
        c = (ring + 1) * segments + next_segment
        d = (ring + 1) * segments + segment
        add_face((a, b, c, d), 0, ((segment / segments, ring / rings),
                                     ((segment + 1) / segments, ring / rings),
                                     ((segment + 1) / segments, (ring + 1) / rings),
                                     (segment / segments, (ring + 1) / rings)))


def catmull(points, t):
    span = min(len(points) - 2, int(t * (len(points) - 1)))
    local = t * (len(points) - 1) - span
    p0 = points[max(0, span - 1)]
    p1 = points[span]
    p2 = points[span + 1]
    p3 = points[min(len(points) - 1, span + 2)]
    return 0.5 * ((2 * p1) + (-p0 + p2) * local
                  + (2 * p0 - 5 * p1 + 4 * p2 - p3) * local ** 2
                  + (-p0 + 3 * p1 - 3 * p2 + p3) * local ** 3)


def lock(controls, width, depth, material):
    controls = [Vector(point) for point in controls]
    base = len(vertices)
    sections = 24
    sides = 6
    for section in range(sections + 1):
        t = section / sections
        point = catmull(controls, t)
        taper = max(0.025, (1 - t ** 3) ** 0.7)
        taper *= min(1, 0.35 + 3 * t)
        for side in range(sides):
            angle = 2 * math.pi * side / sides
            vertices.append((point.x + width * taper * math.cos(angle),
                             point.y + depth * taper * math.sin(angle), point.z))
    for section in range(sections):
        for side in range(sides):
            next_side = (side + 1) % sides
            a = base + section * sides + side
            b = base + section * sides + next_side
            c = base + (section + 1) * sides + next_side
            d = base + (section + 1) * sides + side
            add_face((a, b, c, d), material,
                     ((side / sides, section / sections),
                      ((side + 1) / sides, section / sections),
                      ((side + 1) / sides, (section + 1) / sections),
                      (side / sides, (section + 1) / sections)))


# Curtain-like back hair, with a few brighter strands for depth.
for index in range(27):
    ratio = (index - 13) / 13
    wave = math.sin(index * 2.3) * 0.016
    lock(((ratio * 0.068, 0.035, 1.720),
          (ratio * 0.095, 0.100, 1.585),
          (ratio * 0.130 + wave, 0.135, 1.385),
          (ratio * 0.145 - wave, 0.155, 1.182),
          (ratio * 0.164 + wave, 0.165, 1.015 + 0.045 * math.sin(index))),
         0.0085 if index % 3 else 0.011, 0.008,
         2 if index % 7 == 0 else (1 if index % 3 == 0 else 0))

# Front locks descend beside the cheeks to about the waist.
for side in (-1, 1):
    for index in range(8):
        reach = index / 7
        wave = 0.014 * math.sin(index * 2.1)
        lock(((side * (0.043 + reach * 0.019), -0.012, 1.720),
              (side * (0.079 + reach * 0.039), -0.081 + reach * 0.012, 1.590),
              (side * (0.090 + reach * 0.066 + wave), -0.095 + reach * 0.048, 1.405),
              (side * (0.115 + reach * 0.080 - wave), -0.070 + reach * 0.065, 1.238),
              (side * (0.125 + reach * 0.098 + wave), -0.046 + reach * 0.075,
               1.060 + 0.066 * reach + 0.025 * math.sin(index))),
             0.008 + 0.0015 * (index % 3), 0.006,
             2 if index in (1, 6) else (1 if index in (3, 7) else 0))

# Fine flyaways break up the silhouette and curl away from the shoulder.
for side in (-1, 1):
    for index in range(4):
        lock(((side * 0.071, 0.045, 1.705),
              (side * 0.124, 0.091, 1.526),
              (side * (0.181 + 0.010 * index), 0.118, 1.340),
              (side * (0.211 + 0.013 * index), 0.133, 1.156)),
             0.0038, 0.003, 2 if index == 1 else 0)

# Soft staggered fringe frames the eyes without covering them entirely.
for index in range(15):
    ratio = (index - 7) / 7
    end_z = 1.627 + 0.024 * abs(ratio) + 0.007 * math.sin(index * 1.8)
    lock(((ratio * 0.030, -0.006, 1.755),
          (ratio * 0.052, -0.057, 1.718),
          (ratio * 0.071, -0.087, 1.670),
          (ratio * 0.077, -0.093, end_z)),
         0.0078, 0.004, 2 if index % 5 == 0 else 0)

mesh = bpy.data.meshes.new("Hair_BlueSilver_Long_Mesh")
mesh.from_pydata(vertices, [], faces)
mesh.update()
for material in materials:
    mesh.materials.append(material)
uv = mesh.uv_layers.new(name="HairUV")
for polygon, material_index, coordinates in zip(mesh.polygons, face_materials, face_uvs):
    polygon.material_index = material_index
    polygon.use_smooth = True
    for loop_index, coordinate in zip(polygon.loop_indices, coordinates):
        uv.data[loop_index].uv = coordinate
hair = bpy.data.objects.new("Hair_BlueSilver_Long", mesh)
bpy.context.scene.collection.objects.link(hair)
group = hair.vertex_groups.new(name="CC_Base_Head")
group.add(list(range(len(mesh.vertices))), 1.0, "REPLACE")
modifier = hair.modifiers.new("HeadRig", "ARMATURE")
modifier.object = armature

# Three pale blue flowers sit on the right side of the fringe.
clip_material = bpy.data.materials.new("Hair_Flower_Blue")
clip_material.diffuse_color = (0.22, 0.42, 0.72, 1)
clip_material.use_nodes = True
clip_bsdf = next(node for node in clip_material.node_tree.nodes if node.type == "BSDF_PRINCIPLED")
clip_bsdf.inputs["Base Color"].default_value = (0.22, 0.42, 0.72, 1)
clip_bsdf.inputs["Roughness"].default_value = 0.43
flower_parts = []
for flower_index in range(3):
    center = Vector((0.090 + 0.005 * flower_index, -0.100, 1.694 - 0.022 * flower_index))
    for petal_index in range(5):
        angle = 2 * math.pi * petal_index / 5
        bpy.ops.mesh.primitive_uv_sphere_add(segments=12, ring_count=8,
                                             location=center + Vector((0.007 * math.cos(angle),
                                                                       -0.004, 0.007 * math.sin(angle))))
        petal = bpy.context.object
        petal.scale = (0.005, 0.003, 0.008)
        bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
        petal.data.materials.append(clip_material)
        flower_parts.append(petal)
bpy.ops.object.select_all(action="DESELECT")
for part in flower_parts:
    part.select_set(True)
bpy.context.view_layer.objects.active = flower_parts[0]
bpy.ops.object.join()
clip = bpy.context.object
clip.name = "Hair_Flower_Clip"
clip_group = clip.vertex_groups.new(name="CC_Base_Head")
clip_group.add(list(range(len(clip.data.vertices))), 1.0, "REPLACE")
clip_modifier = clip.modifiers.new("HeadRig", "ARMATURE")
clip_modifier.object = armature

bpy.context.scene.frame_set(1)
bpy.context.preferences.filepaths.save_version = 0
bpy.ops.wm.save_as_mainfile(filepath=str(destination))
print("PREPARED_BASE", destination, "hair_vertices", len(hair.data.vertices),
      "face_keys", len(face_keys))
