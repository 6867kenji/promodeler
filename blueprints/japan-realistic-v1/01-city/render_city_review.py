"""Blender: -- BUILD_DIR VIEW,... . Update selected review cameras from source."""

from dataclasses import asdict
import json
import sys
from pathlib import Path

import bpy

args = sys.argv[sys.argv.index("--") + 1:]
output, requested = Path(args[0]).resolve(), set(args[1].split(","))
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from assets.city import render
from promodeler.kernel.compile import CompiledScene
from promodeler.kernel.render import render_views
from promodeler.contact_sheet import make_contact_sheet

bpy.ops.wm.open_mainfile(filepath=str(output / "model.blend"))
for obj in list(bpy.context.scene.objects):
    if obj.type == "LIGHT":
        bpy.data.objects.remove(obj, do_unlink=True)
parts = {obj.name: obj for obj in bpy.context.scene.objects if obj.type == "MESH"}
scene = CompiledScene(root=bpy.data.objects.get("root"), parts=parts)
settings = json.loads((output / "recipe.json").read_text(encoding="utf-8"))["render"]
settings["views"] = []
settings["cameras"] = [asdict(c) for c in render.cameras if c.id in requested]
if len(settings["cameras"]) != len(requested):
    raise ValueError("Unknown review camera")
report = json.loads((output / "report.json").read_text(encoding="utf-8"))
renders = Path(report["renders"][0]["path"]).parent
results = {r["view"]: r for r in render_views(scene, settings, str(renders))}
report["renders"] = [results.get(r["view"], r) for r in report["renders"]]
report.setdefault("reviewCameraOverrides", {}).update({c["id"]: c for c in settings["cameras"]})
report["contact_sheet"] = make_contact_sheet(report, renders / "contact_sheet.png")
(output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
print("CITY_REVIEW_RENDERED", ",".join(results), flush=True)
