"""Deterministic verification renders: named environments, auto-framed fixed views and diagnostic passes.

Environments are procedural so builds stay self-contained: ``studio`` is a
vertical gradient with an area key light, ``overcast`` a bright soft dome,
``sunny`` and ``sunset`` use Blender's physical sky with a matching sun.
An ``.hdr``/``.exr`` path uses that image. Passes render every view with
the shaded material, a neutral clay override, a wireframe, world-space
normals or a UV checker.
"""

from __future__ import annotations

import math
import os
import time

import bpy
from mathutils import Vector

from promodeler.core.diagnostics import ModelingError

from .compile import CompiledScene
from .fields import sock
from .materials import ensure_node_tree
from .report import world_bounds

# Camera directions in Blender space (Z up, -Y toward the viewer).
VIEW_DIRECTIONS = {
    "perspective": Vector((1.0, -1.2, 0.8)),
    "front": Vector((0.0, -1.0, 0.0)),
    "back": Vector((0.0, 1.0, 0.0)),
    "side": Vector((1.0, 0.0, 0.0)),
    "top": Vector((0.0, -0.0001, 1.0)),
}


def _world_tree():
    scene = bpy.context.scene
    world = bpy.data.worlds.new("world")
    scene.world = world
    tree = ensure_node_tree(world)
    tree.nodes.clear()
    output = tree.nodes.new("ShaderNodeOutputWorld")
    background = tree.nodes.new("ShaderNodeBackground")
    tree.links.new(background.outputs["Background"], output.inputs["Surface"])
    return world, tree, background


def _gradient_world(stops, level: float) -> None:
    _, tree, background = _world_tree()
    coords = tree.nodes.new("ShaderNodeTexCoord")
    separate = tree.nodes.new("ShaderNodeSeparateXYZ")
    tree.links.new(coords.outputs["Generated"], separate.inputs["Vector"])
    remap = tree.nodes.new("ShaderNodeMapRange")
    remap.clamp = True
    tree.links.new(separate.outputs["Z"], sock(remap, "Value"))
    sock(remap, "From Min").default_value = -1.0
    sock(remap, "From Max").default_value = 1.0
    ramp = tree.nodes.new("ShaderNodeValToRGB")
    ramp.color_ramp.interpolation = "EASE"
    elements = ramp.color_ramp.elements
    while len(elements) > 1:
        elements.remove(elements[-1])
    for index, (position, value, tint) in enumerate(stops):
        element = elements[0] if index == 0 else elements.new(position)
        element.position = position
        element.color = (value * level * tint[0], value * level * tint[1], value * level * tint[2], 1.0)
    tree.links.new(sock(remap, "Result", output=True), sock(ramp, "Fac"))
    tree.links.new(sock(ramp, "Color", output=True), background.inputs["Color"])
    background.inputs["Strength"].default_value = 1.0


def _probe_world_radiance(scene: CompiledScene, elevation: float, rotation: float) -> float:
    """Mean linear radiance of the world seen from the scene center toward the given direction.

    Renders a tiny frame with every object hidden, so environments can be
    exposed consistently whatever units a Blender version's sky uses.
    """
    import tempfile

    bscene = bpy.context.scene
    hidden = [o for o in bscene.objects if not o.hide_render]
    for obj in hidden:
        obj.hide_render = True
    camera = bpy.data.objects.new("probe", bpy.data.cameras.new("probe"))
    camera.data.angle = math.radians(90)
    direction = Vector((math.cos(elevation) * math.sin(rotation), math.cos(elevation) * math.cos(rotation), math.sin(elevation)))
    camera.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()
    bscene.collection.objects.link(camera)
    saved = (bscene.camera, bscene.render.resolution_x, bscene.render.resolution_y, bscene.render.engine,
             bscene.view_settings.view_transform, bscene.render.filepath, bscene.render.image_settings.file_format)
    path = os.path.join(tempfile.gettempdir(), "promodeler_world_probe.png")
    try:
        bscene.camera = camera
        bscene.render.resolution_x = bscene.render.resolution_y = 32
        bscene.render.engine = "BLENDER_EEVEE"
        bscene.view_settings.view_transform = "Standard"
        bscene.render.image_settings.file_format = "PNG"
        bscene.render.filepath = path
        bpy.ops.render.render(write_still=True)
        image = bpy.data.images.load(path)
        pixels = image.pixels[:]
        bpy.data.images.remove(image)
    finally:
        (bscene.camera, bscene.render.resolution_x, bscene.render.resolution_y, bscene.render.engine,
         bscene.view_settings.view_transform, bscene.render.filepath, bscene.render.image_settings.file_format) = saved
        bpy.data.objects.remove(camera, do_unlink=True)
        for obj in hidden:
            obj.hide_render = False

    def decode(c: float) -> float:
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

    count = len(pixels) // 4
    luminance = sum(0.2126 * decode(pixels[i * 4]) + 0.7152 * decode(pixels[i * 4 + 1]) + 0.0722 * decode(pixels[i * 4 + 2])
                    for i in range(count)) / max(count, 1)
    return luminance


def _expose_world(scene: CompiledScene, elevation: float, rotation: float, target_display: float) -> float:
    """Scale the world's Background strength so the sky opposite the sun reads ``target_display`` in sRGB.

    Returns the resulting mean linear radiance of that sky region.
    """
    world = bpy.context.scene.world
    background = next(n for n in world.node_tree.nodes if n.type == "BACKGROUND")
    background.inputs["Strength"].default_value = 1.0
    measured = _probe_world_radiance(scene, elevation, rotation + math.pi)
    target = (target_display + 0.055) / 1.055
    target = target ** 2.4 if target_display > 0.04045 else target_display / 12.92
    if measured <= 1e-9:
        raise ModelingError("render.environment", "The environment renders black; cannot expose it.")
    strength = target / measured
    background.inputs["Strength"].default_value = strength
    ground = world.node_tree.nodes.get("ground")
    if ground is not None:
        albedo = (0.36, 0.32, 0.27)
        ground.outputs[0].default_value = tuple(target * a / strength for a in albedo) + (1.0,)
    return target


def _sky_world(elevation: float, rotation: float, strength: float, turbidity: float = 2.5, dust: float = 0.4) -> None:
    _, tree, background = _world_tree()
    sky = tree.nodes.new("ShaderNodeTexSky")
    # Blender 5 renamed the physical sky model; 4.x calls it Nishita.
    for sky_type in ("MULTIPLE_SCATTERING", "NISHITA", "SINGLE_SCATTERING"):
        try:
            sky.sky_type = sky_type
            break
        except TypeError:
            continue
    else:
        raise ModelingError("render.environment", "This Blender has no physical sky model.")
    sky.sun_disc = False
    sky.sun_elevation = elevation
    sky.sun_rotation = rotation
    sky.altitude = 0.0
    sky.air_density = 1.0
    sky.ozone_density = 1.0
    # Haze parameter: "aerosol_density" in Blender 5, "dust_density" in 4.x.
    for attribute in ("aerosol_density", "dust_density"):
        if hasattr(sky, attribute):
            setattr(sky, attribute, dust)
            break
    # The physical sky has no ground: below the horizon it is black. Fill the
    # lower hemisphere with a dim constant ground; ``_expose_world`` sets its
    # value relative to the calibrated sky so exposure stays consistent.
    # (EEVEE evaluates sky nodes by view direction only, so a second sky
    # node cannot sample the horizon color.)
    ground = tree.nodes.new("ShaderNodeRGB")
    ground.name = "ground"
    ground.outputs[0].default_value = (0.0, 0.0, 0.0, 1.0)
    coords = tree.nodes.new("ShaderNodeTexCoord")
    separate = tree.nodes.new("ShaderNodeSeparateXYZ")
    tree.links.new(coords.outputs["Generated"], separate.inputs["Vector"])
    blend = tree.nodes.new("ShaderNodeMapRange")
    blend.interpolation_type = "SMOOTHSTEP"
    blend.clamp = True
    tree.links.new(separate.outputs["Z"], sock(blend, "Value"))
    sock(blend, "From Min").default_value = -0.03
    sock(blend, "From Max").default_value = 0.01
    mix = tree.nodes.new("ShaderNodeMix")
    mix.data_type = "RGBA"
    mix.blend_type = "MIX"
    tree.links.new(sock(blend, "Result", output=True), sock(mix, "Factor_Float"))
    tree.links.new(ground.outputs[0], sock(mix, "A_Color"))
    tree.links.new(sky.outputs["Color"], sock(mix, "B_Color"))
    tree.links.new(sock(mix, "Result_Color", output=True), background.inputs["Color"])
    background.inputs["Strength"].default_value = strength


def _hdri_world(path: str, strength: float = 1.0) -> None:
    if not os.path.isfile(path):
        raise ModelingError("render.environment", f"HDRI file not found: {path}")
    _, tree, background = _world_tree()
    image = bpy.data.images.load(path)
    node = tree.nodes.new("ShaderNodeTexEnvironment")
    node.image = image
    coords = tree.nodes.new("ShaderNodeTexCoord")
    tree.links.new(coords.outputs["Generated"], node.inputs["Vector"])
    tree.links.new(node.outputs["Color"], background.inputs["Color"])
    background.inputs["Strength"].default_value = strength


def _area_key(center: Vector, radius: float, direction: Vector, energy_scale: float, color=(1.0, 1.0, 1.0)) -> None:
    key = bpy.data.lights.new("key", "AREA")
    key.shape = "RECTANGLE"
    key.size = radius * 3.0
    key.size_y = radius * 2.0
    key.color = color
    distance = radius * 4.0
    key.energy = energy_scale * distance * distance
    obj = bpy.data.objects.new("key", key)
    obj.location = center + direction.normalized() * distance
    obj.rotation_euler = (center - obj.location).to_track_quat("-Z", "Y").to_euler()
    bpy.context.scene.collection.objects.link(obj)


def _sun(elevation: float, rotation: float, energy: float, angle: float, color=(1.0, 1.0, 1.0)) -> None:
    sun = bpy.data.lights.new("sun", "SUN")
    sun.energy = energy
    sun.angle = angle
    sun.color = color
    obj = bpy.data.objects.new("sun", sun)
    # Blender sun lamps shine along their local -Z; match the sky's sun position.
    direction = Vector((math.cos(elevation) * math.sin(rotation), math.cos(elevation) * math.cos(rotation), math.sin(elevation)))
    obj.rotation_euler = (-direction).to_track_quat("-Z", "Y").to_euler()
    bpy.context.scene.collection.objects.link(obj)


def setup_environment(scene: CompiledScene, settings: dict, bounds) -> None:
    lo, hi = bounds
    center = (lo + hi) * 0.5
    radius = max((hi - lo).length * 0.5, 1e-3)
    level = sum(settings["background"]) / 3.0
    environment = settings["environment"]
    warm = (1.0, 0.98, 0.95)
    cool = (0.9, 0.95, 1.0)
    if environment == "studio":
        _gradient_world(((0.0, 0.35, warm), (0.45, 0.85, warm), (0.55, 1.6, warm), (0.75, 1.15, cool), (1.0, 1.4, cool)), level)
        _area_key(center, radius, Vector((-0.8, -0.9, 1.1)), 60.0)
        _sun(math.radians(60), math.radians(150), 1.2, math.radians(8))
    elif environment == "overcast":
        _gradient_world(((0.0, 0.5, warm), (0.5, 1.6, warm), (1.0, 2.6, cool)), level)
        _area_key(center, radius, Vector((-0.4, -0.6, 1.4)), 25.0)
    elif environment == "sunny":
        # sun_rotation 0 places the sun toward +Y (behind the front view); -145 degrees puts it front-left.
        elevation, rotation = math.radians(48), math.radians(-145)
        _sky_world(elevation, rotation, 1.0)
        sky = _expose_world(scene, elevation, rotation, 1.3 * level)
        # Clear-sky direct sunlight is several times the diffuse sky irradiance (pi * radiance).
        _sun(elevation, rotation, 6.0 * math.pi * sky, math.radians(0.53), (1.0, 0.96, 0.9))
    elif environment == "sunset":
        elevation, rotation = math.radians(7), math.radians(-125)
        _sky_world(elevation, rotation, 1.0, turbidity=4.0, dust=1.5)
        sky = _expose_world(scene, elevation, rotation, 1.1 * level)
        _sun(elevation, rotation, 2.0 * math.pi * sky, math.radians(0.53), (1.0, 0.72, 0.5))
    else:
        _hdri_world(environment, strength=1.0)
        _expose_world(scene, math.radians(20), 0.0, 1.2 * level)


def setup_engine(settings: dict) -> None:
    scene = bpy.context.scene
    if settings["engine"] == "cycles":
        scene.render.engine = "CYCLES"
        scene.cycles.device = "CPU"
        scene.cycles.samples = max(settings["samples"], 32)
        scene.cycles.seed = 0
        scene.cycles.use_denoising = True
    else:
        scene.render.engine = "BLENDER_EEVEE"
        eevee = getattr(scene, "eevee", None)
        if eevee is not None and hasattr(eevee, "taa_render_samples"):
            eevee.taa_render_samples = settings["samples"]
        if eevee is not None and hasattr(eevee, "use_shadows"):
            eevee.use_shadows = True
    scene.render.resolution_x = settings["resolution"]
    scene.render.resolution_y = settings["resolution"]
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGBA"
    scene.render.film_transparent = False


def frame_camera(camera: bpy.types.Object, direction: Vector, bounds) -> None:
    lo, hi = bounds
    center = (lo + hi) * 0.5
    radius = max((hi - lo).length * 0.5, 1e-3)
    fov = camera.data.angle
    distance = radius / math.sin(fov * 0.5) * 1.15
    direction = direction.normalized()
    camera.location = center + direction * distance
    camera.rotation_euler = (center - camera.location).to_track_quat("-Z", "Y").to_euler()
    camera.data.clip_start = max(distance * 0.01, 1e-4)
    camera.data.clip_end = distance * 10.0


# --- diagnostic passes --------------------------------------------------------


def _clay_material() -> bpy.types.Material:
    mat = bpy.data.materials.new("diag:clay")
    tree = ensure_node_tree(mat)
    tree.nodes.clear()
    output = tree.nodes.new("ShaderNodeOutputMaterial")
    bsdf = tree.nodes.new("ShaderNodeBsdfPrincipled")
    bsdf.inputs["Base Color"].default_value = (0.55, 0.55, 0.55, 1.0)
    bsdf.inputs["Roughness"].default_value = 0.6
    tree.links.new(bsdf.outputs["BSDF"], output.inputs["Surface"])
    return mat


def _normals_material() -> bpy.types.Material:
    mat = bpy.data.materials.new("diag:normals")
    tree = ensure_node_tree(mat)
    tree.nodes.clear()
    output = tree.nodes.new("ShaderNodeOutputMaterial")
    emission = tree.nodes.new("ShaderNodeEmission")
    geometry = tree.nodes.new("ShaderNodeNewGeometry")
    scale = tree.nodes.new("ShaderNodeVectorMath")
    scale.operation = "MULTIPLY_ADD"
    scale.inputs[1].default_value = (0.5, 0.5, 0.5)
    scale.inputs[2].default_value = (0.5, 0.5, 0.5)
    tree.links.new(geometry.outputs["Normal"], scale.inputs[0])
    tree.links.new(scale.outputs[0], emission.inputs["Color"])
    tree.links.new(emission.outputs["Emission"], output.inputs["Surface"])
    return mat


def _uv_material() -> bpy.types.Material:
    mat = bpy.data.materials.new("diag:uv")
    tree = ensure_node_tree(mat)
    tree.nodes.clear()
    output = tree.nodes.new("ShaderNodeOutputMaterial")
    emission = tree.nodes.new("ShaderNodeEmission")
    checker = tree.nodes.new("ShaderNodeTexChecker")
    checker.inputs["Scale"].default_value = 24.0
    checker.inputs["Color1"].default_value = (0.9, 0.9, 0.9, 1.0)
    checker.inputs["Color2"].default_value = (0.2, 0.45, 0.8, 1.0)
    coords = tree.nodes.new("ShaderNodeTexCoord")
    tree.links.new(coords.outputs["UV"], checker.inputs["Vector"])
    tree.links.new(checker.outputs["Color"], emission.inputs["Color"])
    tree.links.new(emission.outputs["Emission"], output.inputs["Surface"])
    return mat


def _wire_material() -> bpy.types.Material:
    mat = bpy.data.materials.new("diag:wire")
    tree = ensure_node_tree(mat)
    tree.nodes.clear()
    output = tree.nodes.new("ShaderNodeOutputMaterial")
    emission = tree.nodes.new("ShaderNodeEmission")
    emission.inputs["Color"].default_value = (0.02, 0.02, 0.03, 1.0)
    tree.links.new(emission.outputs["Emission"], output.inputs["Surface"])
    return mat


class _PassState:
    """Applies and reverts scene changes for one diagnostic pass."""

    def __init__(self, scene: CompiledScene, settings: dict, bounds) -> None:
        self.scene = scene
        self.settings = settings
        self.view_layer = bpy.context.view_layer
        self.render = bpy.context.scene.render
        self.engine = self.render.engine
        self.view_transform = bpy.context.scene.view_settings.view_transform
        lo, hi = bounds
        self.radius = max((hi - lo).length * 0.5, 1e-3)
        self.saved_materials = {obj: list(obj.data.materials) for obj in scene.parts.values()}
        self.wire_modifiers: list[tuple[bpy.types.Object, str]] = []

    def apply(self, name: str) -> None:
        self.revert()
        if name == "shaded":
            return
        if name == "clay":
            self.view_layer.material_override = _clay_material()
        elif name == "normals":
            self.view_layer.material_override = _normals_material()
            bpy.context.scene.view_settings.view_transform = "Standard"
        elif name == "uv":
            self.view_layer.material_override = _uv_material()
            bpy.context.scene.view_settings.view_transform = "Standard"
        elif name == "wireframe":
            # Clay faces with the mesh edges drawn as thin dark tubes by a temporary Wireframe modifier.
            clay = _clay_material()
            wire = _wire_material()
            for obj in self.scene.parts.values():
                mesh = obj.data
                for slot in range(len(mesh.materials)):
                    mesh.materials[slot] = clay
                mesh.materials.append(wire)
                mod = obj.modifiers.new("diag:wireframe", "WIREFRAME")
                mod.thickness = self.radius * 0.0035
                mod.use_replace = False
                mod.use_even_offset = False
                mod.use_relative_offset = False
                mod.material_offset = len(mesh.materials) - 1
                self.wire_modifiers.append((obj, mod.name))
        else:
            raise ModelingError("render.pass", f"Unknown render pass {name!r}.")

    def revert(self) -> None:
        self.view_layer.material_override = None
        self.render.engine = self.engine
        bpy.context.scene.view_settings.view_transform = self.view_transform
        for obj, name in self.wire_modifiers:
            mod = obj.modifiers.get(name)
            if mod is not None:
                obj.modifiers.remove(mod)
        self.wire_modifiers.clear()
        for obj, materials in self.saved_materials.items():
            mesh = obj.data
            while len(mesh.materials) > len(materials):
                mesh.materials.pop()
            for slot, material in enumerate(materials):
                mesh.materials[slot] = material


def render_views(scene: CompiledScene, settings: dict, out_dir: str) -> list[dict]:
    bounds = world_bounds(scene)
    if bounds is None:
        return []
    setup_engine(settings)
    setup_environment(scene, settings, bounds)
    camera = bpy.data.objects.new("camera", bpy.data.cameras.new("camera"))
    bpy.context.scene.collection.objects.link(camera)
    bpy.context.scene.camera = camera
    passes = settings.get("passes") or ["shaded"]
    state = _PassState(scene, settings, bounds)
    results = []
    if scene.armature is not None:
        from . import rig as rigging
        rigging.apply_pose(scene, settings.get("pose"))
    try:
        for pass_name in passes:
            state.apply(pass_name)
            for view in settings["views"]:
                frame_camera(camera, VIEW_DIRECTIONS[view], bounds)
                filename = f"{view}.png" if pass_name == "shaded" else f"{view}_{pass_name}.png"
                path = os.path.join(out_dir, filename)
                bpy.context.scene.render.filepath = path
                started = time.perf_counter()
                bpy.ops.render.render(write_still=True)
                elapsed = time.perf_counter() - started
                written = os.path.isfile(path) and os.path.getsize(path) > 0
                results.append({
                    "view": view,
                    "pass": pass_name,
                    "path": path,
                    "written": written,
                    "bytes": os.path.getsize(path) if written else 0,
                    "seconds": round(elapsed, 3),
                })
    finally:
        state.revert()
        if scene.armature is not None:
            from . import rig as rigging
            rigging.apply_pose(scene, None)
    return results
