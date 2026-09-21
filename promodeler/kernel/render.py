"""Deterministic verification renders: fixed lights, auto-framed fixed views."""

from __future__ import annotations

import math
import os
import time

import bpy
from mathutils import Vector

from .compile import CompiledScene
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
    scene = bpy.context.scene
    world = bpy.data.worlds.new("world")
    scene.world = world
    tree = ensure_node_tree(world)
    node = next((n for n in tree.nodes if n.type == "BACKGROUND"), None) or tree.nodes.new("ShaderNodeBackground")
    output = next((n for n in tree.nodes if n.type == "OUTPUT_WORLD"), None) or tree.nodes.new("ShaderNodeOutputWorld")
    if not any(l.to_node == output for l in tree.links):
        tree.links.new(node.outputs["Background"], output.inputs["Surface"])
    node.inputs["Color"].default_value = (*background, 1.0)
    node.inputs["Strength"].default_value = 1.0


def setup_lights() -> None:
    collection = bpy.context.scene.collection
    for name, energy, rotation in (
        ("key", 3.0, (math.radians(55), math.radians(8), math.radians(-35))),
        ("fill", 0.8, (math.radians(70), math.radians(-10), math.radians(140))),
    ):
        light = bpy.data.lights.new(name, "SUN")
        light.energy = energy
        light.angle = math.radians(5)
        obj = bpy.data.objects.new(name, light)
        obj.rotation_euler = rotation
        collection.objects.link(obj)


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
    setup_world(settings["background"])
    setup_lights()
    setup_engine(settings)
    bounds = world_bounds(scene)
    if bounds is None:
        return []
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
