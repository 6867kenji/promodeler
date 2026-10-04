"""Blender-side compiler for an authored canonical character base.

Invoked only by ``canonical.build``.  No procedural human geometry is made
here: every exported mesh originates in the selected GLB or Blend file.
"""

from __future__ import annotations

from array import array
import json
import math
import sys
import tempfile
import traceback
from pathlib import Path

import bpy
import bmesh
from mathutils import Matrix, Vector


def _color(hex_color: str) -> tuple[float, float, float, float]:
    values = [int(hex_color[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    linear = [v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4 for v in values]
    return (*linear, 1.0)


def _shape_key(name: str, weight: float) -> None:
    found = False
    for obj in bpy.data.objects:
        if obj.type == "MESH" and obj.data.shape_keys:
            block = obj.data.shape_keys.key_blocks.get(name)
            if block:
                block.value = max(0.0, min(1.0, weight))
                found = True
    if not found:
        raise ValueError(f"Shape key {name!r} is missing from the canonical base")


def _bone(name: str, axis: str, scale: float) -> None:
    found = False
    for obj in bpy.data.objects:
        if obj.type == "ARMATURE" and name in obj.pose.bones:
            index = "XYZ".index(axis.upper())
            obj.pose.bones[name].scale[index] = scale
            found = True
    if not found:
        raise ValueError(f"Bone {name!r} is missing from the canonical base")


def _parameters(recipe: dict, manifest: dict) -> None:
    # Authored Blend files may store their editing shape keys at 1.0. A
    # recipe's neutral value must start from the actual Basis, not that saved
    # viewport state (which can combine opposite face shapes at once).
    for spec in manifest.get("parameters", {}).values():
        for shape in spec.get("shapeKeys", []):
            _shape_key(shape["name"], 0.0)
        for bone in spec.get("bones", []):
            _bone(bone["name"], bone.get("axis", "Y"), 1.0)
    for path, spec in manifest.get("parameters", {}).items():
        group, _, key = path.partition(".")
        if group not in ("face", "body") or key not in recipe[group]:
            continue
        value = recipe[group][key]
        for shape in spec.get("shapeKeys", []):
            side = shape.get("side", "positive")
            amount = max(0.0, (value - 0.5) * 2) if side == "positive" else max(0.0, (0.5 - value) * 2)
            _shape_key(shape["name"], amount * shape.get("factor", 1.0))
        for bone in spec.get("bones", []):
            low, high = bone.get("scale", [0.9, 1.1])
            _bone(bone["name"], bone.get("axis", "Y"), low + (high - low) * value)


def _modules(recipe: dict, manifest: dict) -> None:
    for name in manifest.get("excludeObjects", []):
        obj = bpy.data.objects.get(name)
        if obj:
            bpy.data.objects.remove(obj, do_unlink=True)
    for path, choices in manifest.get("modules", {}).items():
        group, _, key = path.partition(".")
        if group not in ("appearance", "wardrobe"):
            continue
        selected = recipe[group].get(key)
        keep = set(choices.get(selected, []))
        all_objects = {name for names in choices.values() for name in names}
        missing = keep - set(bpy.data.objects.keys())
        if missing:
            raise ValueError(f"Canonical module objects missing: {sorted(missing)}")
        for name in all_objects - keep:
            obj = bpy.data.objects.get(name)
            if obj:
                bpy.data.objects.remove(obj, do_unlink=True)
    for path, choices in manifest.get("bodyMasks", {}).items():
        group, _, key = path.partition(".")
        selected = recipe.get(group, {}).get(key)
        for name in choices.get(selected, []):
            obj = bpy.data.objects.get(name)
            if obj:
                bpy.data.objects.remove(obj, do_unlink=True)
    for slot, name in (("top", "Bra"), ("bottom", "Underwear_Bottoms")):
        if not recipe.get("underwear", {}).get(slot, True):
            obj = bpy.data.objects.get(name)
            if obj:
                bpy.data.objects.remove(obj, do_unlink=True)
    for path, choices in manifest.get("bodyMeshMasks", {}).items():
        group, _, key = path.partition(".")
        for mask in choices.get(recipe.get(group, {}).get(key), []):
            obj = bpy.data.objects.get(mask["object"])
            vertex_group = obj.vertex_groups.get(mask["vertexGroup"]) if obj and obj.type == "MESH" else None
            if vertex_group is None:
                raise ValueError(f"Canonical cloth coverage group missing: {mask}")
            covered = {v.index for v in obj.data.vertices
                       if any(g.group == vertex_group.index and g.weight > 0.5 for g in v.groups)}
            bpy.ops.object.select_all(action="DESELECT")
            obj.select_set(True)
            bpy.context.view_layer.objects.active = obj
            bpy.ops.object.mode_set(mode="EDIT")
            bpy.ops.mesh.select_all(action="DESELECT")
            mesh = bmesh.from_edit_mesh(obj.data)
            mesh.verts.ensure_lookup_table()
            for face in mesh.faces:
                face.select_set(all(v.index in covered for v in face.verts))
            bmesh.update_edit_mesh(obj.data, loop_triangles=False, destructive=False)
            # Edit-mode deletion preserves all corresponding shape-key data.
            bpy.ops.mesh.delete(type="ONLY_FACE")
            bpy.ops.object.mode_set(mode="OBJECT")
    selected_accessories = set(recipe.get("accessories", []))
    for accessory, names in manifest.get("accessories", {}).items():
        if accessory in selected_accessories:
            missing = set(names) - set(bpy.data.objects.keys())
            if missing:
                raise ValueError(f"Canonical accessory objects missing: {sorted(missing)}")
        else:
            for name in names:
                obj = bpy.data.objects.get(name)
                if obj:
                    bpy.data.objects.remove(obj, do_unlink=True)


def _materials(recipe: dict, manifest: dict) -> None:
    def adjust_texture(socket, target: tuple[float, ...], channels: tuple[int, ...]) -> bool:
        """Retint a directly linked texture while retaining its painted detail."""
        link = next((item for item in socket.links), None)
        if link is None:
            return False
        node = link.from_node
        if node.type in ("SEPARATE_COLOR", "SEPRGB"):
            source = next((item.from_node for item in node.inputs[0].links), None)
            if source is None or source.type != "TEX_IMAGE":
                raise ValueError(f"Unsupported texture graph for {socket.name}")
            node = source
        if node.type != "TEX_IMAGE" or node.image is None:
            raise ValueError(f"Unsupported texture graph for {socket.name}")
        image = node.image
        pixels = array("f", [0.0]) * (image.size[0] * image.size[1] * 4)
        image.pixels.foreach_get(pixels)
        stride = max(1, image.size[0] * image.size[1] // 20000)
        samples = [i * 4 for i in range(0, image.size[0] * image.size[1], stride)
                   if pixels[i * 4 + 3] > 0.01]
        if not samples:
            raise ValueError(f"Empty texture for {socket.name}")
        averages = [sum(pixels[i + channel] for i in samples) / len(samples)
                    for channel in channels]
        ratios = [desired / max(average, 0.01) for desired, average in zip(target, averages)]
        for i in range(0, len(pixels), 4):
            if pixels[i + 3] <= 0.01:
                continue
            for channel, ratio in zip(channels, ratios):
                pixels[i + channel] = min(1.0, max(0.0, pixels[i + channel] * ratio))
        copy = image.copy()
        copy.name = image.name + "_canonical"
        copy.pixels.foreach_set(pixels)
        copy.update()
        copy.pack()
        node.image = copy
        return True

    sources = {
        "skin": ("skinTone", "roughnessSkin"),
        "hair": ("hairColor", None),
        "eyes": ("eyeColor", None),
        "lips": ("lipColor", None),
    }
    for role, names in manifest.get("materials", {}).items():
        if role not in sources:
            continue
        color_key, rough_key = sources[role]
        for name in names:
            mat = bpy.data.materials.get(name)
            if mat is None:
                raise ValueError(f"Material {name!r} is missing from the canonical base")
            mat.use_nodes = True
            bsdf = next((node for node in mat.node_tree.nodes if node.type == "BSDF_PRINCIPLED"), None)
            if bsdf is None:
                raise ValueError(f"Material {name!r} has no Principled BSDF")
            if color_key in recipe["material"]:
                color = _color(recipe["material"][color_key])
                if not adjust_texture(bsdf.inputs["Base Color"], color[:3], (0, 1, 2)):
                    bsdf.inputs["Base Color"].default_value = color
                mat.diffuse_color = color
            if rough_key and rough_key in recipe["material"]:
                socket = bsdf.inputs["Roughness"]
                if socket.is_linked:
                    output = socket.links[0].from_socket.name
                    channel = 1 if output in ("Green", "G") else 0
                    adjust_texture(socket, (recipe["material"][rough_key],), (channel,))
                else:
                    socket.default_value = recipe["material"][rough_key]
    for path, targets in manifest.get("shaderInputs", {}).items():
        group, _, key = path.partition(".")
        if group not in recipe or key not in recipe[group]:
            continue
        for target in targets:
            material = bpy.data.materials.get(target["material"])
            node = material.node_tree.nodes.get(target["node"]) if material and material.use_nodes else None
            if node is None or target["input"] not in node.inputs:
                raise ValueError(f"Shader input {target} is missing from the canonical base")
            node.inputs[target["input"]].default_value = recipe[group][key]


def _limit_textures(objects: list, maximum: int | None, output: Path) -> None:
    if maximum is None:
        return
    images = set()
    for obj in objects:
        if obj.type != "MESH":
            continue
        for slot in obj.material_slots:
            material = slot.material
            if material and material.use_nodes:
                images.update(node.image for node in material.node_tree.nodes
                              if node.type == "TEX_IMAGE" and node.image)
    with tempfile.TemporaryDirectory(dir=output) as temporary:
        for index, image in enumerate(images):
            width, height = image.size
            if max(width, height) <= maximum:
                continue
            ratio = maximum / max(width, height)
            image.scale(max(1, round(width * ratio)), max(1, round(height * ratio)))
            image.filepath_raw = str(Path(temporary) / f"texture_{index}.png")
            image.file_format = "PNG"
            image.save()
            image.pack()


def _preview(path: Path) -> None:
    for obj in list(bpy.context.scene.objects):
        if obj.type == "LIGHT":
            bpy.data.objects.remove(obj, do_unlink=True)
    meshes = [obj for obj in bpy.context.scene.objects if obj.type == "MESH"]
    if not meshes:
        raise ValueError("Canonical base has no mesh objects")
    points = [obj.matrix_world @ Vector(corner) for obj in meshes for corner in obj.bound_box]
    minimum = Vector((min(p[i] for p in points) for i in range(3)))
    maximum = Vector((max(p[i] for p in points) for i in range(3)))
    center = (minimum + maximum) / 2
    height = max(0.5, maximum.z - minimum.z)
    camera_data = bpy.data.cameras.new("CanonicalPreview")
    camera = bpy.data.objects.new("CanonicalPreview", camera_data)
    bpy.context.scene.collection.objects.link(camera)
    camera.location = center + Vector((height * 1.15, -height * 2.5, height * 0.55))
    direction = center - camera.location
    camera.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()
    camera_data.type = "ORTHO"
    width = max(maximum.x - minimum.x, maximum.y - minimum.y)
    camera_data.ortho_scale = max(height * 1.42, width * 2.1)
    bpy.context.scene.camera = camera
    for index, offset in enumerate(((2, -3, 4), (-2, -1, 3))):
        light_data = bpy.data.lights.new(f"PreviewLight{index}", "AREA")
        light = bpy.data.objects.new(f"PreviewLight{index}", light_data)
        bpy.context.scene.collection.objects.link(light)
        light.location = center + Vector(offset)
        light.rotation_euler = (center - light.location).to_track_quat("-Z", "Y").to_euler()
        light_data.energy = 650 if index == 0 else 350
        light_data.shape = "DISK"
        light_data.size = 3
    scene = bpy.context.scene
    scene.render.engine = "CYCLES"
    scene.cycles.samples = 16
    scene.render.resolution_x = 512
    scene.render.resolution_y = 768
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.filepath = str(path)
    scene.world = bpy.data.worlds.new("CanonicalPreviewWorld")
    scene.world.color = (0.6, 0.6, 0.6)
    scene.use_nodes = False
    bpy.ops.render.render(write_still=True)


def main() -> None:
    model_path, out_path, do_render = sys.argv[sys.argv.index("--") + 1:]
    out = Path(out_path)
    recipe = json.loads((out / "recipe.json").read_text(encoding="utf-8"))
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    report = {"status": "failed", "base": manifest["id"], "model": str(model_path)}
    try:
        bpy.ops.object.select_all(action="SELECT")
        bpy.ops.object.delete(use_global=False)
        if model_path.lower().endswith(".blend"):
            bpy.ops.wm.open_mainfile(filepath=model_path, load_ui=False, use_scripts=False)
        elif model_path.lower().endswith(".fbx"):
            bpy.ops.import_scene.fbx(filepath=model_path)
            # FBX base exports may carry a one-frame preview pose and keyed
            # expressions. Start a reusable base in its bind pose instead.
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
        else:
            bpy.ops.import_scene.gltf(filepath=model_path)
        _parameters(recipe, manifest)
        _modules(recipe, manifest)
        _materials(recipe, manifest)
        for obj in bpy.context.selected_objects:
            obj.select_set(False)
        # Rigify control widgets can live in excluded collections. They are not
        # model geometry and cannot be selected by the active view layer.
        objects = [obj for obj in bpy.context.scene.objects
                   if obj.type in ("MESH", "ARMATURE")
                   and not obj.name.startswith("WGT-")
                   and bpy.context.view_layer.objects.get(obj.name) is not None]
        if not any(obj.type == "MESH" for obj in objects):
            raise ValueError("Canonical base has no mesh to export")
        # Some authored Blend files hide the armature only in the viewport.
        # glTF's selected export omits it unless this local visibility is reset.
        for obj in objects:
            if obj.type == "ARMATURE":
                obj.hide_set(False)
                obj.hide_viewport = False
        _limit_textures(objects, manifest.get("textureMaxSize"), out)
        for obj in objects:
            obj.select_set(True)
        bpy.ops.export_scene.gltf(filepath=str(out / "model.glb"), export_format="GLB",
                                  use_selection=True, export_apply=False,
                                  export_morph=manifest.get("exportMorphs", True),
                                  export_all_influences=manifest.get("exportAllInfluences", False),
                                  export_animations=not model_path.lower().endswith(".fbx"))
        if manifest.get("requireSkin", False):
            with (out / "model.glb").open("rb") as exported:
                exported.seek(12)
                json_length = int.from_bytes(exported.read(4), "little")
                if exported.read(4) != b"JSON" or not json.loads(exported.read(json_length)).get("skins"):
                    raise ValueError("Canonical rigged base exported without a glTF skin")
        if do_render == "1":
            _preview(out / "preview.png")
        report.update({"status": "ok", "objects": len(objects),
                       "glb_bytes": (out / "model.glb").stat().st_size,
                       "preview": "preview.png" if do_render == "1" else None})
    except Exception as exc:
        report["error"] = {"code": "canonical.compile", "message": str(exc)}
        traceback.print_exc()
    (out / "build.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if report["status"] != "ok":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
