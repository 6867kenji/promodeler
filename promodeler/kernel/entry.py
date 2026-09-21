"""Entry point executed by ``blender -b --python entry.py -- <project_root> <recipe.json> <out_dir> <renders_dir> <bake|reuse>``.

Always writes ``report.json``. On failure the report carries ``error`` and the
process exits nonzero, so the caller never mistakes a crash for a result.

Pipeline order: compile -> freeze geometry -> UVs and bakes -> LODs -> rig
-> numerical report -> renders -> exports.
"""

from __future__ import annotations

import json
import os
import sys
import time
import traceback


def main() -> int:
    args = sys.argv[sys.argv.index("--") + 1:]
    project_root, recipe_path, out_dir = args[0], args[1], args[2]
    renders_dir = args[3] if len(args) > 3 else os.path.join(out_dir, "renders")
    reuse_textures = len(args) > 4 and args[4] == "reuse"
    if project_root not in sys.path:
        sys.path.insert(0, project_root)
    os.makedirs(out_dir, exist_ok=True)
    report_path = os.path.join(out_dir, "report.json")
    started = time.perf_counter()
    report: dict = {"status": "failed"}
    try:
        import bpy

        from promodeler import KERNEL_VERSION
        from promodeler.kernel import compile as compiler, export, render, report as reporting, rig, surface

        with open(recipe_path, "r", encoding="utf-8") as f:
            recipe = json.load(f)
        stages: dict = {}

        def stage(name, fn, *args, **kwargs):
            t0 = time.perf_counter()
            result = fn(*args, **kwargs)
            stages[name] = round(time.perf_counter() - t0, 3)
            return result

        stage("compile", lambda: (compiler.reset_scene(), None)[1])
        scene = stage("compile", compiler.compile_recipe, recipe)
        stage("freeze", compiler.freeze_geometry, scene)
        stage("surface", surface.finish, scene, recipe, out_dir, reuse_textures=reuse_textures)
        stage("lods", compiler.build_lods, scene, recipe)
        rig_info = stage("rig", rig.bind_all, scene, recipe)
        report.update(stage("report", reporting.build_report, scene, recipe))
        if rig_info is not None:
            report["rig"] = rig_info
        os.makedirs(renders_dir, exist_ok=True)
        report["renders"] = stage("render", render.render_views, scene, recipe["render"], renders_dir)
        has_clips = bool(recipe["asset"].get("clips"))
        formats = (recipe.get("export") or {}).get("formats", ["glb"])
        report["export"] = stage("export_glb", export.export_gltf, scene, os.path.join(out_dir, "model.glb"), has_clips)
        report["exports"] = {"glb": report["export"]}
        if "usdz" in formats:
            report["exports"]["usdz"] = stage("export_usdz", export.export_usdz, scene, os.path.join(out_dir, "model.usdz"), has_clips)
        report["stages"] = stages
        report["status"] = "ok"
        report["environment"] = {"blender": bpy.app.version_string, "kernel_version": KERNEL_VERSION, "python": sys.version.split()[0]}
        code = 0
    except Exception as exc:  # noqa: BLE001 - the report is the error channel.
        error = exc.to_dict() if hasattr(exc, "to_dict") else {"code": type(exc).__name__, "message": str(exc)}
        error["traceback"] = traceback.format_exc()
        report["error"] = error
        code = 1
    report["seconds"] = round(time.perf_counter() - started, 3)
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    return code


if __name__ == "__main__":
    sys.exit(main())
