"""Blender helper: render a consistent facial closeup from a canonical GLB."""

from __future__ import annotations

import sys
from pathlib import Path

import bpy
from mathutils import Vector


glb_path, image_path = (Path(value) for value in sys.argv[sys.argv.index("--") + 1:])
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=str(glb_path))
rig = next((obj for obj in bpy.data.objects
            if obj.type == "ARMATURE" and "CC_Base_Head" in obj.pose.bones), None)
if rig is None:
    raise RuntimeError("CC_Base_Head is missing from the imported character")
head = rig.matrix_world @ rig.pose.bones["CC_Base_Head"].head
target = head + Vector((0, 0, 0.12))

camera_data = bpy.data.cameras.new("MakeupFaceCamera")
camera = bpy.data.objects.new("MakeupFaceCamera", camera_data)
bpy.context.scene.collection.objects.link(camera)
camera.location = target + Vector((0.10, -0.75, 0.035))
camera.rotation_euler = (target - camera.location).to_track_quat("-Z", "Y").to_euler()
camera_data.type = "ORTHO"
camera_data.ortho_scale = 0.53
bpy.context.scene.camera = camera

for name, location, power, size in (
    ("MakeupKey", target + Vector((0.45, -0.65, 0.45)), 90, 0.8),
    ("MakeupFill", target + Vector((-0.55, -0.3, 0.20)), 45, 0.9),
):
    light_data = bpy.data.lights.new(name, "AREA")
    light_data.energy = power
    light_data.size = size
    light = bpy.data.objects.new(name, light_data)
    bpy.context.scene.collection.objects.link(light)
    light.location = location
    light.rotation_euler = (target - light.location).to_track_quat("-Z", "Y").to_euler()

scene = bpy.context.scene
scene.render.engine = "CYCLES"
scene.cycles.samples = 16
scene.render.resolution_x = 512
scene.render.resolution_y = 512
scene.render.resolution_percentage = 100
scene.render.image_settings.file_format = "PNG"
scene.render.filepath = str(image_path)
scene.world = bpy.data.worlds.new("MakeupWorld")
scene.world.use_nodes = False
scene.world.color = (0.18, 0.18, 0.18)
image_path.parent.mkdir(parents=True, exist_ok=True)
bpy.ops.render.render(write_still=True)
