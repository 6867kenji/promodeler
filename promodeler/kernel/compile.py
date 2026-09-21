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

    # Create objects first, parent afterwards so declaration order is irrelevant.
    for part in asset["parts"]:
        mesh = geometry.build_mesh(f"mesh:{part['id']}", part["shape"], quality)
        geometry.apply_shading(mesh, part["smooth_angle"])
        mesh.materials.append(scene.materials[part["material"]])
        obj = bpy.data.objects.new(part["id"], mesh)
        collection.objects.link(obj)
        geometry.add_modifiers(obj, part["modifiers"])
        scene.parts[part["id"]] = obj

    for part in asset["parts"]:
        obj = scene.parts[part["id"]]
        obj.parent = scene.parts[part["parent"]] if part["parent"] else root
        obj.matrix_parent_inverse.identity()
        obj.matrix_basis = space.author_to_blender_matrix(part["transform"])

    bpy.context.view_layer.update()
    return scene
