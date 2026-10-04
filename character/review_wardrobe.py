"""Import a generated GLB and review cloth deformation in two bounded poses.

Blender: -- MODEL.glb OUTPUT_DIRECTORY
Writes renders and a rig/texture/weight report, without altering the GLB.
"""

import json
import math
import sys
from pathlib import Path

import bpy
from mathutils import Matrix, Quaternion, Vector

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from promodeler.character.canonical_blender import _preview


source, destination = map(Path, sys.argv[sys.argv.index("--") + 1:])
destination.mkdir(parents=True, exist_ok=True)
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=str(source))
rig = next(obj for obj in bpy.context.scene.objects if obj.type == "ARMATURE" and "CC_Base_L_Upperarm" in obj.data.bones)
garments = [obj for obj in bpy.context.scene.objects if obj.type == "MESH" and obj.name.startswith("Wardrobe_")]
hair = [obj for obj in bpy.context.scene.objects if obj.type == "MESH" and obj.name.startswith("Hair_")]
missing = [image.name for image in bpy.data.images if image.source == "FILE" and not image.packed_file
           and not Path(bpy.path.abspath(image.filepath)).is_file()]
if missing or not garments:
    raise ValueError(f"Review requires garments and complete textures: {missing}")
weights = {obj.name: sum(bool(v.groups) for v in obj.data.vertices) / max(1, len(obj.data.vertices)) for obj in garments + hair}
if any(ratio < .999 for ratio in weights.values()):
    raise ValueError(f"Unweighted garment or hair vertices: {weights}")


def snapshot(obj):
    depsgraph = bpy.context.evaluated_depsgraph_get()
    evaluated = obj.evaluated_get(depsgraph)
    mesh = evaluated.to_mesh()
    stride = max(1, len(mesh.vertices) // 4000)
    points = [evaluated.matrix_world @ mesh.vertices[i].co for i in range(0, len(mesh.vertices), stride)]
    evaluated.to_mesh_clear()
    return points


baseline = {obj.name: snapshot(obj) for obj in garments + hair}
report = {"source": str(source), "bones": len(rig.data.bones), "images": len(bpy.data.images),
          "missingImages": missing, "weightedRatio": weights, "poses": {}}
poses = {
    "arms-raised": (("CC_Base_L_Upperarm", (0, 1, 0), -55), ("CC_Base_R_Upperarm", (0, 1, 0), 55)),
    "bent-knee": (("CC_Base_L_Thigh", (1, 0, 0), -30), ("CC_Base_L_Calf", (1, 0, 0), 55),
                  ("CC_Base_L_Upperarm", (0, 1, 0), -20), ("CC_Base_Head", (0, 0, 1), 15)),
}
for name, settings in poses.items():
    for bone in rig.pose.bones:
        bone.matrix_basis = Matrix.Identity(4)
    for bone_name, axis, degrees in settings:
        bone = rig.pose.bones[bone_name]
        transform = rig.matrix_world @ bone.bone.matrix_local
        local_axis = transform.inverted().to_3x3() @ Vector(axis)
        bone.rotation_mode = "QUATERNION"
        bone.rotation_quaternion = Quaternion(local_axis.normalized(), math.radians(degrees))
    bpy.context.view_layer.update()
    movement = {}
    for obj in garments + hair:
        current = snapshot(obj)
        movement[obj.name] = round(max((a - b).length for a, b in zip(baseline[obj.name], current)), 5)
    report["poses"][name] = {"maximumDisplacementM": movement, "render": name + ".png"}
    _preview(destination / (name + ".png"))
if not any(value > .01 for pose in report["poses"].values() for value in pose["maximumDisplacementM"].values()):
    raise ValueError("Clothing did not respond to the rig")
(destination / "review.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
print("WARDROBE_REVIEW_OK", source, weights)
