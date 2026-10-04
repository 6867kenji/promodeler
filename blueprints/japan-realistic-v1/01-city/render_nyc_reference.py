"""Render a small textured review image of the prepared NYC reference Blend."""

import sys
from pathlib import Path

import bpy


source, output = map(Path, sys.argv[sys.argv.index("--") + 1:])
bpy.ops.wm.open_mainfile(filepath=str(source))
scene = bpy.context.scene
scene.render.engine = "BLENDER_EEVEE"
scene.render.resolution_x = 960
scene.render.resolution_y = 540
scene.render.resolution_percentage = 100
scene.render.image_settings.file_format = "PNG"
scene.render.filepath = str(output)
if not scene.camera:
    scene.camera = bpy.data.objects.get("Camera")
if not scene.camera:
    raise RuntimeError("Reference scene has no camera")
output.parent.mkdir(parents=True, exist_ok=True)
bpy.ops.render.render(write_still=True)
print("RENDERED_NYC_REFERENCE", output)
