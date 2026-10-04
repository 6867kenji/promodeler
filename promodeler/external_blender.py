"""Blender side of ``promodeler external export``; keep original sources read-only."""
import bpy
import json
import sys
from pathlib import Path

source, output, receipt = map(Path, sys.argv[sys.argv.index('--') + 1:])
extension = source.suffix.lower()
if extension == '.blend':
    bpy.ops.wm.open_mainfile(filepath=str(source), load_ui=False, use_scripts=False)
elif extension == '.fbx':
    # Blender 5.2's FBX importer still writes a removed Cycles light setting
    # for files containing lights. External GLB export only keeps mesh/rig data.
    import io_scene_fbx.import_fbx as import_fbx
    import_fbx.blen_read_light = lambda *_: bpy.data.lights.new('Reference FBX Light', 'POINT')
    bpy.ops.import_scene.fbx(filepath=str(source), use_image_search=True)
elif extension == '.obj':
    bpy.ops.wm.obj_import(filepath=str(source))
else:
    raise ValueError('Unsupported source format: ' + extension)

if source.name == 'Gates_And_Vending.fbx':
    for obj in bpy.context.scene.objects:
        if obj.name == 'Ground_Plane' and obj.type == 'MESH':
            obj.hide_render = True

if source.name == 'Indoor+Plants.fbx':
    # This FBX omits the leaf image links even though the supplied texture
    # folder contains the color, cutout, normal, and gloss maps. It also has
    # an untextured presentation cube that is not part of either plant.
    for obj in bpy.context.scene.objects:
        if obj.type == 'MESH' and obj.name == 'Cube' and len(obj.data.vertices) == 8:
            obj.hide_render = True
    material = bpy.data.materials.get('Indoor_Plant_Leaf')
    if material is None:
        raise RuntimeError('Indoor Plants leaf material missing')
    material.use_nodes = True
    nodes = material.node_tree.nodes
    links = material.node_tree.links
    shader = next((node for node in nodes if node.type == 'BSDF_PRINCIPLED'), None)
    if shader is None:
        raise RuntimeError('Indoor Plants leaf shader missing')
    texture_root = source.parent / 'textures'
    for filename, socket, noncolor in (
        ('Indoor_Plant_Leaf_Color.jpg', 'Base Color', False),
        ('Indoor_Plant_Leaf_Opacity.jpg', 'Alpha', True),
    ):
        image = bpy.data.images.load(str(texture_root / filename), check_existing=True)
        if noncolor:
            image.colorspace_settings.name = 'Non-Color'
        node = nodes.new('ShaderNodeTexImage')
        node.image = image
        links.new(node.outputs['Color'], shader.inputs[socket])
    gloss_image = bpy.data.images.load(str(texture_root / 'Indoor_Plant_Leaf_Glossy.jpg'), check_existing=True)
    gloss_image.colorspace_settings.name = 'Non-Color'
    gloss_texture = nodes.new('ShaderNodeTexImage')
    gloss_texture.image = gloss_image
    invert = nodes.new('ShaderNodeMath')
    invert.operation = 'SUBTRACT'
    invert.inputs[0].default_value = 1.0
    links.new(gloss_texture.outputs['Color'], invert.inputs[1])
    links.new(invert.outputs[0], shader.inputs['Roughness'])
    normal_image = bpy.data.images.load(str(texture_root / 'Indoor_Plant_Leaf_NormalMap.jpg'), check_existing=True)
    normal_image.colorspace_settings.name = 'Non-Color'
    normal_texture = nodes.new('ShaderNodeTexImage')
    normal_texture.image = normal_image
    normal_map = nodes.new('ShaderNodeNormalMap')
    links.new(normal_texture.outputs['Color'], normal_map.inputs['Color'])
    links.new(normal_map.outputs['Normal'], shader.inputs['Normal'])
    material.surface_render_method = 'DITHERED'

if source.name.lower() == 'red maple-corona.fbx':
    # Corona materials arrive without glTF-compatible image links. Rebuild
    # them from the explicit color, opacity, and normal maps in map/.
    for obj in bpy.context.scene.objects:
        if obj.type == 'MESH' and obj.name == 'Cube' and len(obj.data.vertices) == 8:
            obj.hide_render = True
    for material_name in ('Cap_03', 'RedMapleBark', 'RedMapleLeaf_1', 'RedMapleLeaf_2'):
        material = bpy.data.materials.get(material_name + '_Mat')
        if material is None:
            raise RuntimeError('Red Maple material missing: ' + material_name)
        material.use_nodes = True
        nodes = material.node_tree.nodes
        links = material.node_tree.links
        shader = next((node for node in nodes if node.type == 'BSDF_PRINCIPLED'), None)
        if shader is None:
            raise RuntimeError('Red Maple shader missing: ' + material_name)
        for suffix, socket, noncolor in (('', 'Base Color', False), ('_Opacity', 'Alpha', True)):
            path = source.parent / 'map' / (material_name + suffix + '.jpg')
            if not path.is_file():
                if suffix:
                    continue
                raise RuntimeError('Red Maple color map missing: ' + str(path))
            image = bpy.data.images.load(str(path), check_existing=True)
            if noncolor:
                image.colorspace_settings.name = 'Non-Color'
            node = nodes.new('ShaderNodeTexImage')
            node.image = image
            links.new(node.outputs['Color'], shader.inputs[socket])
        normal_path = source.parent / 'map' / (material_name + '_Normal.jpg')
        if normal_path.is_file():
            normal_image = bpy.data.images.load(str(normal_path), check_existing=True)
            normal_image.colorspace_settings.name = 'Non-Color'
            texture = nodes.new('ShaderNodeTexImage')
            texture.image = normal_image
            normal = nodes.new('ShaderNodeNormalMap')
            links.new(texture.outputs['Color'], normal.inputs['Color'])
            links.new(normal.outputs['Normal'], shader.inputs['Normal'])
        if (source.parent / 'map' / (material_name + '_Opacity.jpg')).is_file():
            material.surface_render_method = 'DITHERED'

if source.name == 'HQ Tree and bush garden box outdoor  VOL 07 Vray.FBX':
    # V-Ray wrapper nodes are imported as anonymous "Map #..." images with
    # empty file paths. The mapping was recovered from the FBX connection
    # graph, including the nested color-correction/VRay2Sided wrappers.
    for obj in bpy.context.scene.objects:
        if obj.type == 'MESH' and obj.name == 'Cube' and len(obj.data.vertices) == 8:
            obj.hide_render = True
    mapping_path = Path(__file__).resolve().parents[1] / 'assets' / 'garden_material_map.json'
    mapping = json.loads(mapping_path.read_text(encoding='utf-8'))

    def image_for(paths, *, exclude=()):
        candidates = [value for value in paths if not any(
            Path(value).stem.casefold().endswith(suffix) for suffix in exclude)]
        if not candidates:
            candidates = paths
        if not candidates:
            return None
        relative = min(candidates, key=lambda value: len(Path(value).stem))
        path = source.parent / relative
        if not path.is_file():
            raise FileNotFoundError(path)
        return path

    def attach_texture(material, nodes, links, shader, path, socket, noncolor=False):
        if path is None:
            return
        image = bpy.data.images.load(str(path), check_existing=True)
        if noncolor:
            image.colorspace_settings.name = 'Non-Color'
        texture = nodes.new('ShaderNodeTexImage')
        texture.image = image
        links.new(texture.outputs['Color'], shader.inputs[socket])

    for material_name, slots in mapping.items():
        if not slots or material_name not in bpy.data.materials:
            continue
        material = bpy.data.materials[material_name]
        material.use_nodes = True
        nodes = material.node_tree.nodes
        nodes.clear()
        links = material.node_tree.links
        output_node = nodes.new('ShaderNodeOutputMaterial')
        shader = nodes.new('ShaderNodeBsdfPrincipled')
        shader.inputs['Roughness'].default_value = .78
        links.new(shader.outputs['BSDF'], output_node.inputs['Surface'])
        attach_texture(material, nodes, links, shader,
                       image_for(slots.get('diffuse', []), exclude=('_ao', '_custom', '_gloss')),
                       'Base Color')
        alpha = image_for(slots.get('opacity', []))
        if alpha:
            attach_texture(material, nodes, links, shader, alpha, 'Alpha', True)
            material.surface_render_method = 'DITHERED'
        normal_path = image_for(slots.get('bump', []), exclude=('_ao', '_custom'))
        if normal_path and 'normal' in normal_path.stem.casefold():
            image = bpy.data.images.load(str(normal_path), check_existing=True)
            image.colorspace_settings.name = 'Non-Color'
            texture = nodes.new('ShaderNodeTexImage')
            texture.image = image
            normal = nodes.new('ShaderNodeNormalMap')
            links.new(texture.outputs['Color'], normal.inputs['Color'])
            links.new(normal.outputs['Normal'], shader.inputs['Normal'])
        gloss_path = image_for(slots.get('reflectionGlossiness', []))
        if gloss_path and 'gloss' in gloss_path.stem.casefold():
            image = bpy.data.images.load(str(gloss_path), check_existing=True)
            image.colorspace_settings.name = 'Non-Color'
            texture = nodes.new('ShaderNodeTexImage')
            texture.image = image
            invert = nodes.new('ShaderNodeMath')
            invert.operation = 'SUBTRACT'
            invert.inputs[0].default_value = 1.0
            links.new(texture.outputs['Color'], invert.inputs[1])
            links.new(invert.outputs[0], shader.inputs['Roughness'])

meshes = [obj for obj in bpy.context.scene.objects if obj.type == 'MESH' and not obj.hide_render]
if not meshes:
    raise RuntimeError('No visible mesh objects found')
used_materials = {material for obj in meshes for material in obj.data.materials if material}
used_images = {node.image for material in used_materials if material.use_nodes
               for node in material.node_tree.nodes if node.type == 'TEX_IMAGE' and node.image}
image_files = None
relinked = []
missing = []
for image in used_images:
    if image.source != 'FILE' or image.packed_file:
        continue
    path = Path(bpy.path.abspath(image.filepath, library=image.library)) if image.filepath else None
    if path and path.is_file():
        continue
    if image_files is None:
        image_files = {path.name.casefold(): path for path in source.parent.rglob('*') if path.is_file()}
    name = Path(image.filepath.replace('\\', '/')).name if image.filepath else image.name
    candidate = image_files.get(name.casefold())
    if candidate is None:
        missing.append(image.name)
    else:
        image.filepath = str(candidate)
        image.reload()
        relinked.append(image.name)
if missing:
    # Keep the geometry usable while making incomplete textures explicit in
    # the build receipt. An absent image must not remain as a broken GLB URI.
    for material in used_materials:
        if not material.use_nodes:
            continue
        for node in material.node_tree.nodes:
            if node.type == 'TEX_IMAGE' and node.image and node.image.name in missing:
                node.image = None
    print('EXTERNAL_MISSING_TEXTURES', len(missing), ', '.join(sorted(missing)[:10]), flush=True)

bpy.ops.object.select_all(action='DESELECT')
objects = [obj for obj in bpy.context.scene.objects if obj.type in ('MESH', 'ARMATURE') and not obj.hide_render]
for obj in objects:
    obj.select_set(True)
bpy.ops.export_scene.gltf(filepath=str(output), export_format='GLB', use_selection=True,
                          export_apply=False, export_animations=any(obj.type == 'ARMATURE' for obj in objects))
report = {'status': 'warning' if missing else 'ok',
          'source': str(source), 'glb': str(output), 'bytes': output.stat().st_size,
          'objects': len(objects), 'meshes': len(meshes), 'vertices': sum(len(obj.data.vertices) for obj in meshes),
          'images': sum(image.source == 'FILE' and image.name not in missing for image in used_images),
          'relinkedTextures': relinked,
          'missingTextures': sorted(missing),
          'textureStatus': ('partial_missing_source_textures' if missing and len(missing) < len(used_images)
                            else 'missing_source_textures' if missing
                            else 'linked_or_packed' if any(image.source == 'FILE' for image in used_images)
                            else 'material_only')}
receipt.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
print('EXTERNAL_ASSET_EXPORTED',report['meshes'],report['vertices'],report['images'],flush=True)
