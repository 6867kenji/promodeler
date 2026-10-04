"""Blender: -- BUILD_DIR. Frame the full 500 m plan using the verified Blend."""

import json
import sys
from pathlib import Path

import bpy


output = Path(sys.argv[sys.argv.index("--") + 1]).resolve()
project = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(project))
from promodeler.kernel.compile import CompiledScene
from promodeler.kernel.render import render_views
from promodeler.contact_sheet import make_contact_sheet

bpy.ops.wm.open_mainfile(filepath=str(output / "model.blend"))
for obj in list(bpy.context.scene.objects):
    if obj.type == "LIGHT":
        bpy.data.objects.remove(obj, do_unlink=True)
parts = {obj.name: obj for obj in bpy.context.scene.objects if obj.type == "MESH"}
scene = CompiledScene(root=bpy.data.objects.get("root"), parts=parts)
recipe = json.loads((output / "recipe.json").read_text(encoding="utf-8"))
settings = recipe["render"]
settings["views"] = []
settings["cameras"] = [c for c in settings["cameras"] if c["id"] == "district_plan"]
settings["cameras"][0]["ortho_scale"] = 840
report = json.loads((output / "report.json").read_text(encoding="utf-8"))
previous = next(r for r in report["renders"] if r["view"] == "district_plan")
renders = Path(previous["path"]).parent
result = render_views(scene, settings, str(renders))[0]
report["renders"] = [result if r["view"] == "district_plan" else r for r in report["renders"]]
report["reviewCameraOverrides"] = {"district_plan": {"ortho_scale": 840}}
report["contact_sheet"] = make_contact_sheet(report, renders / "contact_sheet.png")
(output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
print("CITY_PLAN_RENDERED", result["path"], flush=True)
