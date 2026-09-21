"""Deterministic verification renders: a fixed studio environment and auto-framed fixed views.

The environment is a vertical gradient (dark ground, bright horizon,
blue-gray sky) plus a large area key light and a sun fill, so metals and
glossy surfaces show reflections and roughness differences are visible.
"""

from __future__ import annotations

import math
import os
import time

import bpy
from mathutils import Vector

from .compile import CompiledScene
from .fields import sock
from .materials import ensure_node_tree
from .report import world_bounds

# Camera directions in Blender space (Z up, -Y toward the viewer).
VIEW_DIRECTIONS = {
    "perspective": Vector((1.0, -1.2, 0.8)),
    "front": Vector((0.0, -1.0, 0.0)),
    "side": Vector((1.0, 0.0, 0.0)),
    "top": Vector((0.0, -0.0001, 1.0)),
}


def setup_world(background: list[float]) -> None:
    """Gradient environment scaled by the requested background gray level."""
    scene = bpy.context.scene
    world = bpy.data.worlds.new("world")
    scene.world = world
    tree = ensure_node_tree(world)
    tree.nodes.clear()
    output = tree.nodes.new("ShaderNodeOutputWorld")
    node = tree.nodes.new("ShaderNodeBackground")
    tree.links.new(node.outputs["Background"], output.inputs["Surface"])
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
    level = sum(background) / 3.0
    stops = (
        (0.0, 0.35 * level),
        (0.45, 0.85 * level),
        (0.55, 1.6 * level),
        (0.75, 1.15 * level),
        (1.0, 1.4 * level),
    )
    elements = ramp.color_ramp.elements
    while len(elements) > 1:
        elements.remove(elements[-1])
    for index, (position, value) in enumerate(stops):
        element = elements[0] if index == 0 else elements.new(position)
        element.position = position
        tint = (1.0, 0.98, 0.95) if position < 0.6 else (0.9, 0.95, 1.0)
        element.color = (value * tint[0], value * tint[1], value * tint[2], 1.0)
    tree.links.new(sock(remap, "Result", output=True), sock(ramp, "Fac"))
    tree.links.new(sock(ramp, "Color", output=True), node.inputs["Color"])
    node.inputs["Strength"].default_value = 1.0


def setup_lights(bounds) -> None:
    """A soft area key light scaled to the asset plus a crisp sun fill."""
    collection = bpy.context.scene.collection
    lo, hi = bounds
    center = (lo + hi) * 0.5
    radius = max((hi - lo).length * 0.5, 1e-3)
    key = bpy.data.lights.new("key", "AREA")
    key.shape = "RECTANGLE"
    key.size = radius * 3.0
    key.size_y = radius * 2.0
    distance = radius * 4.0
    key.energy = 60.0 * distance * distance
    key_obj = bpy.data.objects.new("key", key)
    key_obj.location = center + Vector((-0.8, -0.9, 1.1)).normalized() * distance
    key_obj.rotation_euler = (center - key_obj.location).to_track_quat("-Z", "Y").to_euler()
    collection.objects.link(key_obj)

    fill = bpy.data.lights.new("fill", "SUN")
    fill.energy = 1.2
    fill.angle = math.radians(8)
    fill_obj = bpy.data.objects.new("fill", fill)
    fill_obj.rotation_euler = (math.radians(60), math.radians(-10), math.radians(150))
    collection.objects.link(fill_obj)


def setup_engine(settings: dict) -> None:
    scene = bpy.context.scene
    if settings["engine"] == "cycles":
        scene.render.engine = "CYCLES"
        scene.cycles.samples = settings["samples"]
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


def render_views(scene: CompiledScene, settings: dict, out_dir: str) -> list[dict]:
    bounds = world_bounds(scene)
    if bounds is None:
        return []
    setup_world(settings["background"])
    setup_lights(bounds)
    setup_engine(settings)
    camera = bpy.data.objects.new("camera", bpy.data.cameras.new("camera"))
    bpy.context.scene.collection.objects.link(camera)
    bpy.context.scene.camera = camera
    results = []
    for view in settings["views"]:
        frame_camera(camera, VIEW_DIRECTIONS[view], bounds)
        path = os.path.join(out_dir, f"{view}.png")
        bpy.context.scene.render.filepath = path
        started = time.perf_counter()
        bpy.ops.render.render(write_still=True)
        elapsed = time.perf_counter() - started
        written = os.path.isfile(path) and os.path.getsize(path) > 0
        results.append({
            "view": view,
            "path": path,
            "written": written,
            "bytes": os.path.getsize(path) if written else 0,
            "seconds": round(elapsed, 3),
        })
    return results
