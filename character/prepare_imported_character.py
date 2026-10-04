"""Prepare a supplied Rigify Blend for the canonical character exporter.

Run in Blender with: --python prepare_imported_character.py -- SOURCE.blend OUTPUT.blend [FALLBACK_TEXTURE_DIR]
The source Blend and its images are never modified.
"""

import sys
from pathlib import Path

import bpy


args = sys.argv[sys.argv.index("--") + 1:]
source = Path(args[0]).resolve()
destination = Path(args[1]).resolve()
fallback = Path(args[2]).resolve() if len(args) > 2 else None
destination.parent.mkdir(parents=True, exist_ok=True)
bpy.ops.wm.open_mainfile(filepath=str(source))

# A hidden armature is skipped by Blender's glTF exporter even when its meshes
# have armature modifiers and the object is explicitly selected later.
for obj in bpy.data.objects:
    if obj.type == "ARMATURE":
        obj.hide_set(False)
        obj.hide_viewport = False
        obj.hide_render = False

# These are custom-shape meshes used to draw rig controls in the editor.
# They are not part of the character and should not become visible GLB meshes.
controls = [obj for obj in bpy.data.objects
            if obj.type == "MESH" and obj.name.startswith("cs_")
            and not any(mod.type == "ARMATURE" for mod in obj.modifiers)]
for obj in controls:
    bpy.data.objects.remove(obj, do_unlink=True)

repaired = []
for image in list(bpy.data.images):
    if image.source != "FILE" or image.packed_file:
        continue
    path = Path(bpy.path.abspath(image.filepath))
    if path.is_file():
        # Preserve the original texture link after the prepared Blend is saved
        # in a different directory.
        image.filepath = str(path.resolve())
        continue
    if image.name.startswith("studio.exr"):
        # Old Blender versions saved their studio light path in the scene.
        # Canonical previews provide a new world and lights.
        bpy.data.images.remove(image, do_unlink=True)
        continue
    replacement = fallback / path.name if fallback else None
    if replacement and replacement.is_file():
        image.filepath = str(replacement.resolve())
        repaired.append(image.name)
        continue
    raise FileNotFoundError(f"Missing texture for {image.name}: {path}")

bpy.context.preferences.filepaths.save_version = 0
bpy.ops.wm.save_as_mainfile(filepath=str(destination))
print("PREPARED_CHARACTER", destination, "removed_controls", len(controls),
      "repaired_images", ",".join(repaired) or "none")
