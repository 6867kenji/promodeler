"""Prepare the user's new clothing and hairstyles on the existing rigged base.

Run in Blender with ``-- BASE BLOUSE OUTFIT HEADBAND PONYTAIL OUTPUT``.
Source assets and the v3 base are never modified.
"""

import sys
from pathlib import Path

import bpy
from mathutils import Matrix, Vector

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from garment_fit import fit_pant_sections, fit_sleeve_sections


base, blouse, outfit, headband, ponytail, output = map(
    Path, sys.argv[sys.argv.index("--") + 1:]
)
bpy.ops.wm.open_mainfile(filepath=str(base))
body = bpy.data.objects["CC_Base_Body"]
rig = bpy.data.objects["CC3_Base_Plus"]


def add_coverage_group(name, test):
    group = body.vertex_groups.get(name) or body.vertex_groups.new(name=name)
    indices = [v.index for v in body.data.vertices if test(body.matrix_world @ v.co)]
    group.add(indices, 1.0, "REPLACE")
    print("CLOTH_COVERAGE", name, len(indices))


def select(obj):
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj


def new_meshes(before):
    return [obj for obj in bpy.data.objects if obj.type == "MESH" and obj.name not in before]


def fit_world(obj, scale, translation):
    obj.matrix_world = Matrix.Translation(Vector(translation)) @ Matrix.Scale(scale, 4) @ obj.matrix_world
    bpy.context.view_layer.update()
    select(obj)
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)


def fit_chest(obj, torso_materials=None):
    """Expand the chest smoothly, without copying anatomical skin detail."""
    allowed = None if torso_materials is None else {
        i for poly in obj.data.polygons if poly.material_index in torso_materials for i in poly.vertices}
    inverse = obj.matrix_world.inverted()
    for vertex in obj.data.vertices:
        if allowed is not None and vertex.index not in allowed:
            continue
        world = obj.matrix_world @ vertex.co
        low = max(0, min(1, (world.z - 1.15) / 0.09))
        high = max(0, min(1, (world.z - 1.37) / 0.09))
        side = max(0, min(1, (abs(world.x) - 0.18) / 0.08))
        influence = low * low * (3 - 2 * low) * (1 - high * high * (3 - 2 * high)) * (1 - side * side * (3 - 2 * side))
        world.x *= 1 + 0.2 * influence
        world.y = 0.02 + (world.y - 0.02) * (1 + 0.25 * influence) - 0.012 * influence
        vertex.co = inverse @ world
    obj.data.update()


def localize_images(obj, root):
    for material in obj.data.materials:
        if not material or not material.use_nodes:
            continue
        for node in material.node_tree.nodes:
            if node.type != "TEX_IMAGE" or not node.image:
                continue
            image = node.image
            filename = image.filepath.replace("\\", "/").rsplit("/", 1)[-1]
            candidate = root / filename
            if candidate.is_file():
                image.filepath = str(candidate.resolve())
            elif not Path(bpy.path.abspath(image.filepath)).is_file() and not image.packed_file:
                raise FileNotFoundError(f"Missing texture on {obj.name}: {filename}")


def bind_body(obj):
    select(obj)
    for group in body.vertex_groups:
        if obj.vertex_groups.get(group.name) is None:
            obj.vertex_groups.new(name=group.name)
    transfer = obj.modifiers.new("TransferBodyWeights", "DATA_TRANSFER")
    transfer.object = body
    transfer.use_vert_data = True
    transfer.data_types_verts = {"VGROUP_WEIGHTS"}
    transfer.vert_mapping = "POLYINTERP_NEAREST"
    transfer.layers_vgroup_select_src = "ALL"
    transfer.layers_vgroup_select_dst = "NAME"
    bpy.ops.object.modifier_apply(modifier=transfer.name)
    modifier = obj.modifiers.new("CharacterRig", "ARMATURE")
    modifier.object = rig
    if not any(any(group.weight(vertex.index) > 0 for group in obj.vertex_groups
                   if group.index in [item.group for item in vertex.groups])
               for vertex in list(obj.data.vertices)[:10]):
        raise RuntimeError(f"No body weights on {obj.name}")
    print("BOUND_GARMENT", obj.name, len(obj.data.vertices))


def bind_head(obj):
    group = obj.vertex_groups.new(name="CC_Base_Head")
    group.add(list(range(len(obj.data.vertices))), 1.0, "REPLACE")
    modifier = obj.modifiers.new("CharacterRig", "ARMATURE")
    modifier.object = rig
    print("BOUND_HAIR", obj.name, len(obj.data.vertices))


def textured_material(name, color_path, normal_path=None, metallic_path=None, alpha=False):
    material = bpy.data.materials.new(name)
    material.use_nodes = True
    material.surface_render_method = "DITHERED" if alpha else "OPAQUE"
    nodes = material.node_tree.nodes
    nodes.clear()
    output = nodes.new("ShaderNodeOutputMaterial")
    bsdf = nodes.new("ShaderNodeBsdfPrincipled")
    bsdf.inputs["Roughness"].default_value = 0.66
    material.node_tree.links.new(bsdf.outputs["BSDF"], output.inputs["Surface"])

    def texture(path, non_color=False):
        image = bpy.data.images.load(str(path), check_existing=True)
        if non_color:
            image.colorspace_settings.name = "Non-Color"
        node = nodes.new("ShaderNodeTexImage")
        node.image = image
        return node

    color = texture(color_path)
    material.node_tree.links.new(color.outputs["Color"], bsdf.inputs["Base Color"])
    if alpha:
        material.node_tree.links.new(color.outputs["Alpha"], bsdf.inputs["Alpha"])
    if normal_path:
        normal = texture(normal_path, True)
        normal_map = nodes.new("ShaderNodeNormalMap")
        normal_map.inputs["Strength"].default_value = 0.55
        material.node_tree.links.new(normal.outputs["Color"], normal_map.inputs["Color"])
        material.node_tree.links.new(normal_map.outputs["Normal"], bsdf.inputs["Normal"])
    if metallic_path:
        metallic = texture(metallic_path, True)
        material.node_tree.links.new(metallic.outputs["Color"], bsdf.inputs["Metallic"])
    return material


with bpy.data.libraries.load(str(blouse), link=False) as (available, loaded):
    loaded.objects = [name for name in available.objects if name == "BlouseA"]
if len(loaded.objects) != 1 or loaded.objects[0] is None:
    raise RuntimeError("BlouseA mesh was not found")
blouse_obj = loaded.objects[0]
bpy.context.scene.collection.objects.link(blouse_obj)
blouse_obj.name = "Wardrobe_BlouseA"
localize_images(blouse_obj, blouse.parent)
fit_sleeve_sections(blouse_obj, body, set(range(len(blouse_obj.data.materials))), {0})
fit_chest(blouse_obj)
bind_body(blouse_obj)

before = set(bpy.data.objects.keys())
bpy.ops.import_scene.fbx(filepath=str(outfit))
meshes = new_meshes(before)
if len(meshes) != 1:
    raise RuntimeError(f"Expected one outfit mesh, found {len(meshes)}")
outfit_obj = meshes[0]
outfit_obj.name = "Wardrobe_FemaleOutfit"
localize_images(outfit_obj, outfit.parent)
fit_sleeve_sections(outfit_obj, body, {2, 11, 12, 13, 14, 19, 20, 21, 38, 39, 40, 41}, {12})
fit_pant_sections(outfit_obj, body, {0, 3, 4, 5, 6, 7, 8, 9, 10, 16, 17, *range(22, 38)})
fit_chest(outfit_obj, {1, 12, 19})
bind_body(outfit_obj)

before = set(bpy.data.objects.keys())
bpy.ops.import_scene.fbx(filepath=str(headband))
meshes = sorted(new_meshes(before), key=lambda obj: obj.name)
if len(meshes) != 5:
    raise RuntimeError(f"Expected five headband meshes, found {len(meshes)}")
texture_dir = headband.parent.parent / "Texture2D"
headband_material = textured_material(
    "Hair_Headband_Black_Material",
    texture_dir / "set00_hair3_Albedo_black.png",
    texture_dir / "set00_hair3_Normal.png",
    texture_dir / "set00_hair3_Metallic.png",
    alpha=True,
)
for index, obj in enumerate(meshes):
    obj.name = f"Hair_Headband_Black_{index}"
    fit_world(obj, 0.535, (0.019, 0.015, 0.15))
    obj.data.materials.clear()
    obj.data.materials.append(headband_material)
    bind_head(obj)

before = set(bpy.data.objects.keys())
bpy.ops.import_scene.fbx(filepath=str(ponytail))
meshes = new_meshes(before)
if len(meshes) != 1:
    raise RuntimeError(f"Expected one ponytail mesh, found {len(meshes)}")
pony = meshes[0]
pony.name = "Hair_Ponytail_Brown"
fit_world(pony, 7.2, (0, 0.01, 1.40))
localize_images(pony, ponytail.parent / "Textures" / "2k")
bind_head(pony)

# Hide skin covered by opaque clothing at build time. This prevents skin
# protruding through cloth in animated poses, while retaining exposed skin.
add_coverage_group("PM_Cover_Blouse", lambda p: (abs(p.x) < .18 and 1.17 < p.z < 1.46)
                   or (.17 < abs(p.x) < .42 and p.z > 1.2))
add_coverage_group("PM_Cover_FemaleOutfit", lambda p: (.08 < p.z < 1.0)
                   or (.17 < abs(p.x) < .50 and p.z > 1.18)
                   or (abs(p.x) < .18 and 1.20 < p.z < 1.44))

# The supplied textures remain external in the editable Blend source. GLB
# exports embed their textures, including those on the original v3 base.
bpy.context.scene.frame_set(1)
bpy.context.preferences.filepaths.save_version = 0
output.parent.mkdir(parents=True, exist_ok=True)
bpy.ops.wm.save_as_mainfile(filepath=str(output))
print("PREPARED_BASE", output)
