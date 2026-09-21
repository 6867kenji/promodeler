"""Recipe -> Blender scene. Semantic part IDs become object names under a ``root`` empty."""

from __future__ import annotations

from dataclasses import dataclass, field

import bpy

from promodeler.core.diagnostics import ModelingError

from . import geometry, materials, space


@dataclass
class CompiledScene:
    root: bpy.types.Object
    parts: dict[str, bpy.types.Object] = field(default_factory=dict)
    materials: dict[str, bpy.types.Material] = field(default_factory=dict)
    cutters: list[bpy.types.Object] = field(default_factory=list)
    frozen: bool = False


def reset_scene() -> None:
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.unit_settings.system = "METRIC"
    scene.unit_settings.scale_length = 1.0


def compile_recipe(recipe: dict) -> CompiledScene:
    if recipe.get("recipe_version") != 1:
        raise ModelingError("recipe.version", f"Unsupported recipe version {recipe.get('recipe_version')!r}.")
    asset = recipe["asset"]
    quality = (recipe.get("input") or {}).get("quality") or {"curve_segments": 32, "surface_segments": 16}
    collection = bpy.context.scene.collection

    root = bpy.data.objects.new("root", None)
    root.empty_display_type = "PLAIN_AXES"
    collection.objects.link(root)
    scene = CompiledScene(root=root)

    for spec in asset["materials"]:
        scene.materials[spec["id"]] = materials.build_material(spec)

    def cutter_factory(owner: bpy.types.Object, owner_id: str):
        def make_cutter(index: int, spec: dict) -> bpy.types.Object:
            name = f"cutter:{owner_id}:{index}"
            mesh = geometry.build_mesh(f"mesh:{name}", spec["shape"], quality)
            cutter = bpy.data.objects.new(name, mesh)
            collection.objects.link(cutter)
            cutter.parent = owner
            cutter.matrix_parent_inverse.identity()
            cutter.matrix_basis = space.author_to_blender_matrix(spec["transform"])
            cutter.hide_render = True
            cutter.display_type = "WIRE"
            geometry.add_modifiers(cutter, spec["modifiers"], make_cutter=None)
            scene.cutters.append(cutter)
            return cutter
        return make_cutter

    # Create objects first, parent afterwards so declaration order is irrelevant.
    for part in asset["parts"]:
        mesh = geometry.build_mesh(f"mesh:{part['id']}", part["shape"], quality)
        geometry.apply_shading(mesh, part["smooth_angle"])
        mesh.materials.append(scene.materials[part["material"]])
        obj = bpy.data.objects.new(part["id"], mesh)
        collection.objects.link(obj)
        scene.parts[part["id"]] = obj

    for part in asset["parts"]:
        obj = scene.parts[part["id"]]
        obj.parent = scene.parts[part["parent"]] if part["parent"] else root
        obj.matrix_parent_inverse.identity()
        obj.matrix_basis = space.author_to_blender_matrix(part["transform"])
        geometry.add_modifiers(obj, part["modifiers"], make_cutter=cutter_factory(obj, part["id"]))

    bpy.context.view_layer.update()
    return scene


def freeze_geometry(scene: CompiledScene) -> None:
    """Replace each part's mesh with its evaluated result and drop cutters.

    After this, report, render and export all see the identical final
    geometry, and exported meshes keep their semantic names.
    """
    depsgraph = bpy.context.evaluated_depsgraph_get()
    frozen: dict[str, bpy.types.Mesh] = {}
    for part_id, obj in scene.parts.items():
        evaluated = obj.evaluated_get(depsgraph)
        mesh = bpy.data.meshes.new_from_object(evaluated, preserve_all_data_layers=True, depsgraph=depsgraph)
        if len(mesh.polygons) == 0:
            raise ModelingError("geometry.empty", f"Part {part_id!r} has no faces after its modifiers.")
        frozen[part_id] = mesh
    for part_id, obj in scene.parts.items():
        old = obj.data
        obj.modifiers.clear()
        obj.data = frozen[part_id]
        if old.users == 0:
            bpy.data.meshes.remove(old)
        # Rename after the source mesh is gone so the semantic name is not suffixed.
        frozen[part_id].name = f"mesh:{part_id}"
    for cutter in scene.cutters:
        mesh = cutter.data
        bpy.data.objects.remove(cutter, do_unlink=True)
        if mesh is not None and mesh.users == 0:
            bpy.data.meshes.remove(mesh)
    scene.cutters.clear()
    scene.frozen = True
    bpy.context.view_layer.update()
