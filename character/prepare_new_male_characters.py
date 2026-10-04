"""Prepare two supplied male FBX characters as reusable canonical Blend bases.

Run from Blender with ``-- kind source output [shirt_fbx]``. Source files stay
read only; the prepared Blend and its report live in the caller's output area.
"""
import bpy
import json
import math
import sys
from pathlib import Path

from mathutils import Matrix

arguments = sys.argv[sys.argv.index('--') + 1:]
kind, source, destination = arguments[:3]
source, destination = Path(source), Path(destination)
destination.parent.mkdir(parents=True, exist_ok=True)
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.fbx(filepath=str(source), use_image_search=True)


def remove_preview_cubes():
    for obj in list(bpy.context.scene.objects):
        if obj.type == 'MESH' and ((obj.name.startswith('Cube') and len(obj.data.vertices) == 8)
                                   or (obj.name.startswith('Icosphere') and len(obj.data.vertices) <= 100)):
            bpy.data.objects.remove(obj, do_unlink=True)


def vertex_count(obj):
    return sum(any(group.weight > .001 for group in vertex.groups) for vertex in obj.data.vertices)


def material_color(name):
    key = name.casefold()
    if 'skin' in key or 'nails' in key:
        return (.50, .33, .25, 1)
    if 'beard' in key or 'hair' in key:
        return (.07, .045, .03, 1)
    if 'jeans' in key:
        return (.07, .12, .21, 1)
    if 'boots' in key:
        return (.16, .11, .075, 1)
    if 'shirt' in key:
        return (.13, .17, .22, 1)
    if 'eye_occlusion' in key or 'tearline' in key:
        return (.02, .02, .025, 1)
    if 'cornea' in key or 'eye' in key:
        return (.45, .53, .55, 1)
    if 'teeth' in key:
        return (.82, .79, .72, 1)
    if 'tongue' in key:
        return (.43, .17, .20, 1)
    return (.23, .23, .24, 1)


report = {'kind': kind, 'source': str(source), 'output': str(destination)}
remove_preview_cubes()
if kind == 'armor':
    rig = bpy.data.objects['Kevin_actorBUILD']
    rig.animation_data_clear()
    rig.data.pose_position = 'REST'
    bpy.context.scene.frame_set(0)
    bpy.context.view_layer.update()
    # FBX opacity links are interpreted differently by glTF and punched
    # holes into the armor and face on reimport. These parts are solid.
    for material in bpy.data.materials:
        if not material.use_nodes:
            continue
        shader = next((node for node in material.node_tree.nodes
                       if node.type == 'BSDF_PRINCIPLED'), None)
        if shader:
            for link in list(shader.inputs['Alpha'].links):
                material.node_tree.links.remove(link)
            shader.inputs['Alpha'].default_value = 1.0
    correction = Matrix.Rotation(-math.pi / 2, 4, 'X')
    corrected = ('CC_Game_Body', 'Biker_Vest', 'CC_Game_Tongue')
    for name in corrected:
        obj = bpy.data.objects[name]
        graph = bpy.context.evaluated_depsgraph_get()
        mesh = bpy.data.meshes.new_from_object(obj.evaluated_get(graph),
                                               preserve_all_data_layers=True,
                                               depsgraph=graph)
        mesh.transform(obj.matrix_world.inverted() @ correction @ obj.matrix_world)
        obj.modifiers.clear()
        obj.data = mesh
        modifier = obj.modifiers.new('CorrectedArmorRig', 'ARMATURE')
        modifier.object = rig
    body = bpy.data.objects['CC_Game_Body']
    # Legs and feet are completely covered by the armor. This also hides
    # detached skin fragments present in the source rest pose.
    visible = body.vertex_groups.new(name='PM_Armor_VisibleBody')
    keep = [vertex.index for vertex in body.data.vertices
            if (body.matrix_world @ vertex.co).z >= 1.04]
    visible.add(keep, 1., 'REPLACE')
    mask = body.modifiers.new('HideBodyUnderArmor', 'MASK')
    mask.vertex_group = visible.name
    bpy.ops.object.select_all(action='DESELECT')
    body.select_set(True)
    bpy.context.view_layer.objects.active = body
    bpy.ops.object.modifier_move_up(modifier=mask.name)
    bpy.ops.object.modifier_apply(modifier=mask.name)
    report.update({'rig': rig.name, 'bones': len(rig.data.bones), 'correctedMeshes': list(corrected),
                   'visibleBodyVertices': len(keep)})
elif kind == 'dido':
    if len(arguments) < 4:
        raise RuntimeError('Dido requires the new T-shirt FBX path')
    shirt_source = Path(arguments[3])
    rig = bpy.data.objects['Armature']
    rig.animation_data_clear()
    rig.data.pose_position = 'REST'
    bpy.context.scene.frame_set(0)
    bpy.context.view_layer.update()
    # This supplied FBX points to 63 images that are absent from the source
    # folder and has no embedded image payload. Neutral PBR colors avoid pink
    # missing-texture materials while preserving the supplied geometry/rig.
    original_materials = list(bpy.data.materials)
    for material in original_materials:
        material.use_nodes = True
        nodes = material.node_tree.nodes
        nodes.clear()
        output = nodes.new('ShaderNodeOutputMaterial')
        shader = nodes.new('ShaderNodeBsdfPrincipled')
        color = material_color(material.name)
        shader.inputs['Base Color'].default_value = color
        shader.inputs['Roughness'].default_value = .73
        material.diffuse_color = color
        material.node_tree.links.new(shader.outputs['BSDF'], output.inputs['Surface'])
    for image in list(bpy.data.images):
        if image.source == 'FILE' and not image.packed_file and not Path(bpy.path.abspath(image.filepath)).is_file():
            bpy.data.images.remove(image, do_unlink=True)

    before = set(bpy.data.objects)
    bpy.ops.import_scene.fbx(filepath=str(shirt_source), use_image_search=True)
    imported = [obj for obj in bpy.data.objects if obj not in before]
    shirt = next((obj for obj in imported if obj.type == 'MESH' and len(obj.data.vertices) > 1000), None)
    if shirt is None:
        raise RuntimeError('Male T-shirt mesh missing')
    for obj in imported:
        if obj != shirt and obj.type == 'MESH' and len(obj.data.vertices) == 8:
            bpy.data.objects.remove(obj, do_unlink=True)
    shirt.name = 'Wardrobe_Male_Tshirt'
    scale = Matrix.Diagonal((.17, .10, .12, 1.))
    shift = Matrix.Translation((0, .04, -.17))
    refine = Matrix.Translation((0, 0, .902)) @ Matrix.Diagonal((.84, .85, .95, 1.)) @ Matrix.Translation((0, 0, -.902))
    shirt.matrix_world = refine @ shift @ scale @ shirt.matrix_world
    bpy.context.view_layer.update()
    bpy.ops.object.select_all(action='DESELECT')
    shirt.select_set(True)
    bpy.context.view_layer.objects.active = shirt
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    # The clothing source is wider at the shoulder than the supplied body.
    # Extend the outer sleeve edge just enough to overlap the exposed arm.
    for vertex in shirt.data.vertices:
        amount = min(1., max(0., (abs(vertex.co.x) - .30) / .15))
        vertex.co.x *= 1. + .10 * amount
    decimate = shirt.modifiers.new('ReduceSourceTshirt', 'DECIMATE')
    decimate.ratio = .12
    bpy.ops.object.modifier_apply(modifier=decimate.name)
    # The source diffuse alpha cuts random holes through the cotton fabric.
    # Keep the source color/normal maps but render the T-shirt as opaque cloth.
    for material in shirt.data.materials:
        if not material or not material.use_nodes:
            continue
        shader = next((node for node in material.node_tree.nodes
                       if node.type == 'BSDF_PRINCIPLED'), None)
        if shader:
            for link in list(shader.inputs['Alpha'].links):
                material.node_tree.links.remove(link)
            shader.inputs['Alpha'].default_value = 1.0
            shader.inputs['Roughness'].default_value = .82
    body = bpy.data.objects['CC_Base_Body']
    for group in body.vertex_groups:
        if shirt.vertex_groups.get(group.name) is None:
            shirt.vertex_groups.new(name=group.name)
    transfer = shirt.modifiers.new('TransferBodyWeights', 'DATA_TRANSFER')
    transfer.object = body
    transfer.use_vert_data = True
    transfer.data_types_verts = {'VGROUP_WEIGHTS'}
    transfer.vert_mapping = 'POLYINTERP_NEAREST'
    transfer.layers_vgroup_select_src = 'ALL'
    transfer.layers_vgroup_select_dst = 'NAME'
    bpy.ops.object.modifier_apply(modifier=transfer.name)
    armature = shirt.modifiers.new('TshirtRig', 'ARMATURE')
    armature.object = rig
    weighted = vertex_count(shirt)
    if weighted != len(shirt.data.vertices):
        raise RuntimeError(f'T-shirt has {len(shirt.data.vertices)-weighted} unweighted vertices')
    cover = body.vertex_groups.new(name='PM_Cover_Male_Tshirt')
    indices = [vertex.index for vertex in body.data.vertices
               if .88 < (body.matrix_world @ vertex.co).z < 1.65
               and abs((body.matrix_world @ vertex.co).x) < .46]
    cover.add(indices, 1., 'REPLACE')
    report.update({'rig': rig.name, 'bones': len(rig.data.bones),
                   'shirtSource': str(shirt_source), 'shirtVertices': len(shirt.data.vertices),
                   'shirtWeightedVertices': weighted, 'shirtCoverageVertices': len(indices),
                   'missingOriginalTextures': 63})
else:
    raise RuntimeError('Unknown character kind: ' + kind)

for bone in rig.pose.bones:
    bone.matrix_basis = Matrix.Identity(4)
rig.data.pose_position = 'POSE'
bpy.context.view_layer.update()

report['meshes'] = [{'name': obj.name, 'vertices': len(obj.data.vertices),
                     'weightedVertices': vertex_count(obj)} for obj in bpy.context.scene.objects
                    if obj.type == 'MESH']
bpy.ops.file.pack_all()
bpy.context.preferences.filepaths.save_version = 0
bpy.ops.wm.save_as_mainfile(filepath=str(destination), compress=True)
destination.with_suffix('.preparation.json').write_text(
    json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
print('PREPARED_MALE_CHARACTER', kind, destination, flush=True)
