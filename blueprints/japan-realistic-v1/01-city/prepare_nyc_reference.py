"""Relink the supplied NYC block Blend to its extracted texture archive.

Run with Blender: --python prepare_nyc_reference.py -- SOURCE.blend TEXTURES_DIR OUTPUT.blend
The supplied archives and extracted source Blend remain unchanged.
"""

import sys
from pathlib import Path

import bpy


source, texture_dir, destination = sys.argv[sys.argv.index("--") + 1:]
source = Path(source).resolve()
texture_dir = Path(texture_dir).resolve()
destination = Path(destination).resolve()
destination.parent.mkdir(parents=True, exist_ok=True)
bpy.ops.wm.open_mainfile(filepath=str(source))

available = {}
for path in texture_dir.iterdir():
    if path.is_file():
        available.setdefault(path.name.casefold(), []).append(path)

relinked = []
for image in bpy.data.images:
    if image.source != "FILE" or image.packed_file:
        continue
    current = Path(bpy.path.abspath(image.filepath))
    if current.is_file():
        image.filepath = str(current.resolve())
        continue
    matches = available.get(current.name.casefold(), [])
    if len(matches) != 1:
        raise FileNotFoundError(f"Cannot uniquely relink {image.name}: {current}")
    image.filepath = str(matches[0].resolve())
    relinked.append(image.name)

bpy.context.preferences.filepaths.save_version = 0
bpy.ops.wm.save_as_mainfile(filepath=str(destination))
print("PREPARED_NYC_REFERENCE", destination, "relinked", len(relinked))
