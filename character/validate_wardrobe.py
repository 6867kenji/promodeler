"""Re-import the wardrobe example GLBs and verify selections, rigs and images.

Blender: -- OUTPUT_ROOT
"""

import hashlib
import json
import sys
from pathlib import Path

import bpy


root = Path(sys.argv[sys.argv.index("--") + 1]).resolve()
records = []
for directory in sorted((root / "canonical").iterdir()):
    candidates = []
    for output in directory.iterdir():
        report = output / "build.json"
        if report.is_file() and (output / "model.glb").is_file():
            if json.loads(report.read_text(encoding="utf-8")).get("status") == "ok":
                candidates.append(output)
    if not candidates:
        continue
    output = max(candidates, key=lambda p: (p / "model.glb").stat().st_mtime)
    source = output / "model.glb"
    recipe = json.loads((output / "recipe.json").read_text(encoding="utf-8"))
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    expected = [name for key, choice in recipe["wardrobe"].items()
                for name in manifest.get("modules", {}).get("wardrobe." + key, {}).get(choice, [])]
    data = source.read_bytes()
    if data[:4] != b"glTF" or int.from_bytes(data[8:12], "little") != len(data):
        raise ValueError(f"Invalid GLB header: {source}")
    length = int.from_bytes(data[12:16], "little")
    document = json.loads(data[20:20 + length])
    nodes = {node.get("name"): node for node in document.get("nodes", []) if "mesh" in node}
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(source))
    missing_objects = [name for name in expected if name not in nodes]
    missing_images = [image.name for image in bpy.data.images if image.source == "FILE" and not image.packed_file
                      and not Path(bpy.path.abspath(image.filepath)).is_file()]
    rigs = [obj for obj in bpy.context.scene.objects if obj.type == "ARMATURE"]
    expect_rig = "Free_Wardrobe" not in recipe["base"]
    # The importer may create bone control shapes called "shirt" / "jean"
    # before the real meshes, which then receive Blender's ".001" suffix.
    # Check the exact glTF mesh node and the re-imported mesh datablock.
    unskinned = []
    for name in expected:
        if not expect_rig or name not in nodes:
            continue
        mesh_name = document["meshes"][nodes[name]["mesh"]].get("name", name)
        imported = [obj for obj in bpy.context.scene.objects if obj.type == "MESH"
                    and (obj.data.name == mesh_name or obj.data.name.startswith(mesh_name + "."))]
        if "skin" not in nodes[name] or not any(
                any(mod.type == "ARMATURE" and mod.object for mod in obj.modifiers) for obj in imported):
            unskinned.append(name)
    external_images = [image for image in document.get("images", []) if "uri" in image]
    if missing_objects or missing_images or unskinned or (expect_rig and not rigs) or external_images:
        raise ValueError(f"Invalid wardrobe export: {source}, objects={missing_objects}, images={missing_images}, unskinned={unskinned}")
    records.append({"id": recipe["id"], "base": recipe["base"], "glb": str(source),
                    "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data),
                    "bones": sum(len(obj.data.bones) for obj in rigs), "images": len(bpy.data.images),
                    "garments": expected, "status": "ok", "blenderReimport": True, "embeddedImages": True})
    print("WARDROBE_IMPORT_OK", recipe["id"], len(expected), "garments", len(bpy.data.images), "images", flush=True)
(root / "validation.json").write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
print("WARDROBE_VALIDATION_COMPLETE", len(records), flush=True)
