"""Dump MHR LOD1 topology, UVs, skin weights and bone hierarchy from lod1.fbx to cache files.

Run inside Blender once after downloading the MHR assets
(https://github.com/facebookresearch/MHR, Apache 2.0):

    blender -b --python tools/mhr_dump_lod1.py -- external/mhr

The folder must hold ``assets/lod1.fbx``; the script writes
``cache/lod1_topology.npz`` and ``cache/lod1_rig.json`` next to it, which
``promodeler.human.mhr`` reads together with ``assets/mhr_model.pt`` and
``assets/compact_v6_1.model``.
"""
import json
import os
import sys

import bpy
import numpy as np

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
here = os.path.abspath(argv[0] if argv else os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "external", "mhr"))
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.fbx(filepath=os.path.join(here, "assets", "lod1.fbx"))
mesh_obj = next(o for o in bpy.context.scene.objects if o.type == "MESH")
arm_obj = next(o for o in bpy.context.scene.objects if o.type == "ARMATURE")
me = mesh_obj.data
me.calc_loop_triangles()
verts = np.array([v.co[:] for v in me.vertices], dtype=np.float32)  # cm, FBX local space
faces = np.array([t.vertices[:] for t in me.loop_triangles], dtype=np.int32)
uv_layer = me.uv_layers.active
uv_per_loop = np.array([uv_layer.uv[i].vector[:] for i in range(len(me.loops))], dtype=np.float32)
loop_tris = np.array([t.loops[:] for t in me.loop_triangles], dtype=np.int32)
# Skin weights as a dense [n_verts, n_groups] matrix (sparse enough at 100 groups).
group_names = [g.name for g in mesh_obj.vertex_groups]
weights = np.zeros((len(me.vertices), len(group_names)), dtype=np.float32)
for v in me.vertices:
    for g in v.groups:
        weights[v.index, g.group] = g.weight
bones = []
scale = arm_obj.scale[0]
for b in arm_obj.data.bones:
    bones.append({
        "name": b.name,
        "parent": b.parent.name if b.parent else None,
        "head": [c / scale for c in (arm_obj.matrix_world @ b.head_local)[:]],  # back to cm, armature space
        "tail": [c / scale for c in (arm_obj.matrix_world @ b.tail_local)[:]],
    })
out = os.path.join(here, "cache")
os.makedirs(out, exist_ok=True)
np.savez_compressed(os.path.join(out, "lod1_topology.npz"), verts=verts, faces=faces, uv_per_loop=uv_per_loop,
                    loop_tris=loop_tris, weights=weights)
with open(os.path.join(out, "lod1_rig.json"), "w", encoding="utf-8") as f:
    json.dump({"group_names": group_names, "bones": bones, "armature_matrix": [list(r) for r in arm_obj.matrix_world]}, f)
print("DUMP verts", verts.shape, "faces", faces.shape, "groups", len(group_names), "bones", len(bones))
print("DUMP armature matrix", [[round(c, 3) for c in r] for r in arm_obj.matrix_world])
print("DUMP mesh matrix", [[round(c, 3) for c in r] for r in mesh_obj.matrix_world])
