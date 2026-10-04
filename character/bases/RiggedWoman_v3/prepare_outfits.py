"""Add the user's four wardrobe meshes to RiggedWoman_v2 without changing sources.

Run with Blender:
  blender -b --factory-startup --python prepare_outfits.py -- \
    BASE.blend SPORTS.blend THIN.fbx THICK.fbx LINGERIE.obj OUTPUT.blend
"""

import sys
from math import radians
from pathlib import Path

import bpy
from mathutils import Matrix, Vector


base, sports, thin, thick, lingerie, destination = sys.argv[sys.argv.index("--") + 1:]
destination = Path(destination).resolve()
destination.parent.mkdir(parents=True, exist_ok=True)
bpy.ops.wm.open_mainfile(filepath=base)
body = bpy.data.objects["CC_Base_Body"]
source_bra = bpy.data.objects["Bra"]
armature = bpy.data.objects["CC3_Base_Plus"]


def smoothstep(a, b, value):
    t = max(0.0, min(1.0, (value - a) / (b - a)))
    return t * t * (3.0 - 2.0 * t)


# The two supplied outfits were tailored for a smaller bust than the base.
# Expose an actual body shape key so each Recipe can request its fitting size.
bust_fit = body.shape_key_add(name="PM_Bust_Flatten", from_mix=False)
basis = body.data.shape_keys.key_blocks["Basis"]
world_to_local = body.matrix_world.inverted().to_3x3()
adjusted = 0
for index, vertex in enumerate(basis.data):
    world = body.matrix_world @ vertex.co
    x_weight = 1.0 - smoothstep(0.12, 0.22, abs(world.x))
    z_weight = smoothstep(1.17, 1.26, world.z) * (1.0 - smoothstep(1.36, 1.45, world.z))
    front_weight = 1.0 - smoothstep(-0.11, -0.03, world.y)
    influence = x_weight * z_weight * front_weight
    if influence > 0.0001:
        bust_fit.data[index].co += world_to_local @ Vector((0.0, 0.09 * influence, 0.0))
        adjusted += 1
print("BUST_FIT", adjusted, "vertices")


def active_only(obj):
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj


def prepare_scale(obj, factor):
    obj.matrix_world = Matrix.Scale(factor, 4) @ obj.matrix_world
    bpy.context.view_layer.update()
    active_only(obj)
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)


def bind_to_body(obj, source):
    active_only(obj)
    # Blender's Data Transfer modifier writes to existing groups. Create the
    # source group's names first so that NAME matching has a destination.
    for group in source.vertex_groups:
        if obj.vertex_groups.get(group.name) is None:
            obj.vertex_groups.new(name=group.name)
    transfer = obj.modifiers.new("TransferBodyWeights", "DATA_TRANSFER")
    transfer.object = source
    transfer.use_vert_data = True
    transfer.data_types_verts = {"VGROUP_WEIGHTS"}
    transfer.vert_mapping = "POLYINTERP_NEAREST"
    transfer.layers_vgroup_select_src = "ALL"
    transfer.layers_vgroup_select_dst = "NAME"
    bpy.ops.object.modifier_apply(modifier=transfer.name)
    if not obj.vertex_groups:
        raise RuntimeError(f"No skinning weights transferred to {obj.name}")
    modifier = obj.modifiers.new("CharacterRig", "ARMATURE")
    modifier.object = armature
    print("GARMENT_RIG", obj.name, "groups", len(obj.vertex_groups),
          "vertices", len(obj.data.vertices))


def imported_meshes(before):
    return [obj for obj in bpy.data.objects if obj.name not in before and obj.type == "MESH"]


def fix_relative_images(obj, source_dir):
    for material in obj.data.materials:
        if not material or not material.use_nodes:
            continue
        for node in material.node_tree.nodes:
            if node.type != "TEX_IMAGE" or not node.image:
                continue
            image = node.image
            if image.filepath.startswith("//"):
                image.filepath = str((source_dir / image.filepath[2:]).resolve())
            if not Path(bpy.path.abspath(image.filepath)).is_file():
                # Some OBJ files contain absolute paths from the creator's PC.
                local_image = source_dir / image.filepath.replace("\\", "/").split("/")[-1]
                if local_image.is_file():
                    image.filepath = str(local_image.resolve())
            if not Path(bpy.path.abspath(image.filepath)).is_file() and not image.packed_file:
                raise FileNotFoundError(f"Missing garment image: {image.filepath}")


# Append only the garment mesh from the SportsBRA Blend scene.
with bpy.data.libraries.load(sports, link=False) as (available, loaded):
    loaded.objects = [name for name in available.objects if name == "AFJ00004"]
if len(loaded.objects) != 1 or loaded.objects[0] is None:
    raise RuntimeError("SportsBRA mesh AFJ00004 was not found")
sports_obj = loaded.objects[0]
bpy.context.scene.collection.objects.link(sports_obj)
sports_obj.name = "Wardrobe_SportsBRA"
prepare_scale(sports_obj, 0.01)
sports_obj.rotation_euler.x = radians(90)
active_only(sports_obj)
bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
fix_relative_images(sports_obj, Path(sports).parent)
bind_to_body(sports_obj, source_bra)


texture_root = Path(thick).parent / "textures" / "textures"
texture_prefix = "Obj-thick_FABRIC_1_FRONT_3226_"


def medieval_material(name):
    material = bpy.data.materials.new(name)
    material.use_nodes = True
    nodes = material.node_tree.nodes
    nodes.clear()
    output = nodes.new("ShaderNodeOutputMaterial")
    bsdf = nodes.new("ShaderNodeBsdfPrincipled")
    bsdf.inputs["Roughness"].default_value = 0.68
    material.node_tree.links.new(bsdf.outputs["BSDF"], output.inputs["Surface"])

    def image_node(suffix, non_color=False):
        path = texture_root / (texture_prefix + suffix + ".png")
        if not path.is_file():
            raise FileNotFoundError(path)
        image = bpy.data.images.load(str(path), check_existing=True)
        if non_color:
            image.colorspace_settings.name = "Non-Color"
        node = nodes.new("ShaderNodeTexImage")
        node.image = image
        return node

    color = image_node("BaseColor")
    material.node_tree.links.new(color.outputs["Color"], bsdf.inputs["Base Color"])
    roughness = image_node("Roughness", True)
    material.node_tree.links.new(roughness.outputs["Color"], bsdf.inputs["Roughness"])
    metallic = image_node("Metallic", True)
    material.node_tree.links.new(metallic.outputs["Color"], bsdf.inputs["Metallic"])
    normal = image_node("Normal", True)
    normal_map = nodes.new("ShaderNodeNormalMap")
    normal_map.inputs["Strength"].default_value = 0.65
    material.node_tree.links.new(normal.outputs["Color"], normal_map.inputs["Color"])
    material.node_tree.links.new(normal_map.outputs["Normal"], bsdf.inputs["Normal"])
    return material


for source, name in ((thin, "Wardrobe_Medieval_Thin"), (thick, "Wardrobe_Medieval_Thick")):
    before = set(bpy.data.objects.keys())
    bpy.ops.import_scene.fbx(filepath=source)
    meshes = imported_meshes(before)
    if len(meshes) != 1:
        raise RuntimeError(f"Expected one garment mesh in {source}, got {len(meshes)}")
    outfit = meshes[0]
    outfit.name = name
    material = medieval_material(name + "_Fabric")
    outfit.data.materials.clear()
    outfit.data.materials.append(material)
    bind_to_body(outfit, body)


before = set(bpy.data.objects.keys())
bpy.ops.wm.obj_import(filepath=lingerie)
meshes = imported_meshes(before)
if len(meshes) != 1:
    raise RuntimeError(f"Expected one lingerie mesh, got {len(meshes)}")
lingerie_obj = meshes[0]
lingerie_obj.name = "Wardrobe_Lingerie_Set"
prepare_scale(lingerie_obj, 0.001)
fix_relative_images(lingerie_obj, Path(lingerie).parent)
bind_to_body(lingerie_obj, body)

bpy.context.scene.frame_set(1)
bpy.context.preferences.filepaths.save_version = 0
bpy.ops.wm.save_as_mainfile(filepath=str(destination))
print("PREPARED_WARDROBE", destination)
