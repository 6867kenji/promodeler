"""Blender-side compiler. Every module here may import ``bpy``.

The kernel is started fresh for each build with an empty factory scene, so
no state survives between builds. Authoring space is Y up; Blender is Z up.
``space.A2B`` converts authored transforms into Blender's frame and the glTF
exporter converts back, so exported nodes carry the authored transforms.
"""
