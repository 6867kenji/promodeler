"""Recipe -> Blender scene. Semantic part IDs become object names under a ``root`` empty."""

from __future__ import annotations

from dataclasses import dataclass, field

import bpy

from promodeler.core.diagnostics import ModelingError

from . import geometry, materials, space

GENERATED_KINDS = ("scatter", "fur")
OVERLAPPING_KINDS = ("strands",)
SHAPE_TRANSFER_RADIUS = 0.002  # meters; frozen vertices farther from any source vertex get no shape-key delta  # closed shells that may overlap by design; no self-intersection check


@dataclass
class CompiledScene:
    root: bpy.types.Object
    parts: dict[str, bpy.types.Object] = field(default_factory=dict)
    materials: dict[str, bpy.types.Material] = field(default_factory=dict)
    cutters: list[bpy.types.Object] = field(default_factory=list)
    procedural: dict = field(default_factory=dict)  # material id -> ProceduralMaterial
    textures: dict = field(default_factory=dict)  # part id -> channel -> texture metadata
    uv_stats: dict = field(default_factory=dict)  # part id -> coverage/density
    generated: dict = field(default_factory=dict)  # part id -> shape kind for scatter/fur parts
    overlapping: set = field(default_factory=set)  # part ids whose shells overlap by design (strands)
    lods: dict = field(default_factory=dict)  # part id -> [lod objects]
    lod_stats: dict = field(default_factory=dict)  # part id -> [{level, distance, ratio, triangles}]
    armature: bpy.types.Object | None = None
    joints: dict = field(default_factory=dict)
    pose_specs: dict = field(default_factory=dict)
    cloth_frames: int = 0
    file_weights: dict = field(default_factory=dict)  # part id -> (group names, weights [V, G], source vertices) from a MeshFile
    extras: dict = field(default_factory=dict)  # asset extras, written to extras.json and glTF extras
    file_shapes: dict = field(default_factory=dict)  # part id -> ({shape name: deltas}, source vertices) from a MeshFile
    shape_parts: list = field(default_factory=list)  # part ids that carry shape keys after freezing
    frozen: bool = False


def reset_scene() -> None:
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.unit_settings.system = "METRIC"
    scene.unit_settings.scale_length = 1.0
    scene.frame_set(1)


def _hidden_object(name: str, mesh: bpy.types.Mesh, collection) -> bpy.types.Object:
    obj = bpy.data.objects.new(name, mesh)
    collection.objects.link(obj)
    obj.hide_render = True
    obj.display_type = "WIRE"
    return obj


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
    if asset.get("extras"):
        scene.extras = asset["extras"]
        import json
        root["promodeler_extras"] = json.dumps(asset["extras"], ensure_ascii=False)  # exported as node extras

    for spec in asset["materials"]:
        mat, procedural = materials.build_material(spec)
        scene.materials[spec["id"]] = mat
        if procedural is not None:
            scene.procedural[spec["id"]] = procedural

    def cutter_factory(owner: bpy.types.Object, owner_id: str):
        def make_cutter(index: int, spec: dict) -> bpy.types.Object:
            name = f"cutter:{owner_id}:{index}"
            mesh = geometry.build_mesh(f"mesh:{name}", spec["shape"], quality)
            cutter = _hidden_object(name, mesh, collection)
            cutter.parent = owner
            cutter.matrix_parent_inverse.identity()
            cutter.matrix_basis = space.author_to_blender_matrix(spec["transform"])
            geometry.add_modifiers(cutter, spec["modifiers"], make_cutter=None)
            scene.cutters.append(cutter)
            return cutter
        return make_cutter

    # Create objects first, parent afterwards so declaration order is irrelevant.
    for part in asset["parts"]:
        mesh = geometry.build_mesh(f"mesh:{part['id']}", part["shape"], quality)
        if f"mesh:{part['id']}" in geometry.MESH_FILE_WEIGHTS:
            scene.file_weights[part["id"]] = geometry.MESH_FILE_WEIGHTS[f"mesh:{part['id']}"]
        if f"mesh:{part['id']}" in geometry.MESH_FILE_SHAPES:
            scene.file_shapes[part["id"]] = geometry.MESH_FILE_SHAPES[f"mesh:{part['id']}"]
        if part["shape"]["kind"] in OVERLAPPING_KINDS:
            scene.overlapping.add(part["id"])
        if part["shape"]["kind"] not in GENERATED_KINDS:
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

    # Generated parts read another part's evaluated surface through Object Info.
    for part in asset["parts"]:
        shape = part["shape"]
        if shape["kind"] not in GENERATED_KINDS:
            continue
        obj = scene.parts[part["id"]]
        surface = scene.parts[shape["surface"]]
        scene.generated[part["id"]] = shape["kind"]
        if shape["kind"] == "scatter":
            instance_mesh = geometry.build_mesh(f"mesh:instance:{part['id']}", shape["instance"], quality)
            geometry.apply_shading(instance_mesh, part["smooth_angle"])
            instance = _hidden_object(f"instance:{part['id']}", instance_mesh, collection)
            scene.cutters.append(instance)
            group = geometry.build_scatter_group(f"scatter:{part['id']}", shape, surface, instance)
        else:
            group = geometry.build_fur_group(f"fur:{part['id']}", shape, surface)
        modifier = obj.modifiers.new("generate", "NODES")
        modifier.node_group = group

    _simulate_cloth(scene, asset)
    bpy.context.view_layer.update()
    return scene


def _simulate_cloth(scene: CompiledScene, asset: dict) -> None:
    """Give every non-cloth part a collision body and step the timeline through the longest drape."""
    cloth_parts = [p for p in asset["parts"] if any(m["kind"] == "cloth_drape" for m in p["modifiers"])]
    if not cloth_parts:
        return
    frames = max(m["frames"] for p in cloth_parts for m in p["modifiers"] if m["kind"] == "cloth_drape")
    collide = any(m["collide"] for p in cloth_parts for m in p["modifiers"] if m["kind"] == "cloth_drape")
    cloth_ids = {p["id"] for p in cloth_parts}
    if collide:
        for part_id, obj in scene.parts.items():
            if part_id in cloth_ids or part_id in scene.generated:
                continue
            collision = obj.modifiers.new("collision", "COLLISION")
            if collision is None:
                raise ModelingError("cloth.collision", f"Could not add a collision body to {part_id!r}.")
            obj.collision.thickness_outer = 0.002
    bscene = bpy.context.scene
    bscene.frame_start = 1
    bscene.frame_end = max(bscene.frame_end, frames)
    for frame in range(1, frames + 1):
        bscene.frame_set(frame)
    scene.cloth_frames = frames


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
        old_materials = list(old.materials)
        obj.modifiers.clear()
        obj.data = frozen[part_id]
        if old.users == 0:
            bpy.data.meshes.remove(old)
        frozen[part_id].name = f"mesh:{part_id}"
        if len(frozen[part_id].materials) == 0:
            for material in old_materials:
                frozen[part_id].materials.append(material)
        elif part_id in scene.generated:
            for slot in range(len(frozen[part_id].materials)):
                frozen[part_id].materials[slot] = old_materials[0]
    for cutter in scene.cutters:
        mesh = cutter.data
        bpy.data.objects.remove(cutter, do_unlink=True)
        if mesh is not None and mesh.users == 0:
            bpy.data.meshes.remove(mesh)
    scene.cutters.clear()
    scene.frozen = True
    bpy.context.scene.frame_set(1)
    bpy.context.view_layer.update()


def apply_shape_keys(scene: CompiledScene) -> dict:
    """Add the MeshFile shape keys to the frozen parts as relative shape keys (glTF morph targets).

    Modifiers may have changed the vertex count, so every frozen vertex takes the delta of the nearest
    source vertex, like the skin weights.
    """
    import numpy as np

    added: dict = {}
    for part_id, (shapes, source_vertices) in scene.file_shapes.items():
        obj = scene.parts[part_id]
        mesh = obj.data
        count = len(mesh.vertices)
        coords = np.empty(count * 3, dtype=np.float64)
        mesh.vertices.foreach_get("co", coords)
        coords = coords.reshape(-1, 3)
        mapping = None
        keep = None
        if count != len(source_vertices):
            mapping, distance = geometry.nearest_indices(source_vertices, coords, with_distance=True)
            # Vertices created away from the source surface (boolean cavities, cutter faces) get no delta;
            # otherwise a socket wall inherits the lid's motion and bulges over the eyeball.
            keep = (distance <= SHAPE_TRANSFER_RADIUS)[:, None]
        if mesh.shape_keys is None:
            obj.shape_key_add(name="Basis", from_mix=False)
        for name, deltas in shapes.items():
            block = obj.shape_key_add(name=name, from_mix=False)
            moved = coords + (deltas if mapping is None else deltas[mapping] * keep)
            block.data.foreach_set("co", moved.ravel())
            block.value = 0.0
            block.slider_max = 1.0
        mesh.shape_keys.use_relative = True
        scene.shape_parts.append(part_id)
        added[part_id] = list(shapes)
    return added


def build_lods(scene: CompiledScene, recipe: dict) -> None:
    """Decimated copies of frozen parts, parented to the part and hidden from renders."""
    pending = []
    for part in recipe["asset"]["parts"]:
        if not part.get("lods"):
            continue
        source = scene.parts[part["id"]]
        objects = []
        stats = []
        for level, lod in enumerate(part["lods"], start=1):
            mesh = source.data.copy()
            obj = bpy.data.objects.new(f"{part['id']}:lod{level}", mesh)
            bpy.context.scene.collection.objects.link(obj)
            obj.parent = source
            obj.matrix_parent_inverse.identity()
            obj.matrix_basis.identity()
            decimate = obj.modifiers.new("decimate", "DECIMATE")
            decimate.decimate_type = "COLLAPSE"
            decimate.ratio = lod["ratio"]
            decimate.use_collapse_triangulate = True
            objects.append(obj)
            stats.append({"level": level, "distance": lod["distance"], "ratio": lod["ratio"]})
            pending.append((obj, stats[-1]))
        scene.lods[part["id"]] = objects
        scene.lod_stats[part["id"]] = stats
    if not pending:
        return
    bpy.context.view_layer.update()
    depsgraph = bpy.context.evaluated_depsgraph_get()
    for obj, stat in pending:
        evaluated = obj.evaluated_get(depsgraph)
        mesh = bpy.data.meshes.new_from_object(evaluated, preserve_all_data_layers=True, depsgraph=depsgraph)
        old = obj.data
        obj.modifiers.clear()
        obj.data = mesh
        if old.users == 0:
            bpy.data.meshes.remove(old)
        mesh.name = f"mesh:{obj.name}"
        mesh.calc_loop_triangles()
        stat["triangles"] = len(mesh.loop_triangles)
        obj["lod_level"] = stat["level"]
        obj["lod_distance"] = stat["distance"]
        obj.hide_render = True
