"""Entry point executed by ``blender -b --python entry.py -- <project_root> <recipe.json> <out_dir>``.

Always writes ``report.json``. On failure the report carries ``error`` and the
process exits nonzero, so the caller never mistakes a crash for a result.
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
    if project_root not in sys.path:
        sys.path.insert(0, project_root)
    os.makedirs(out_dir, exist_ok=True)
    report_path = os.path.join(out_dir, "report.json")
    started = time.perf_counter()
    report: dict = {"status": "failed"}
    try:
        import bpy

        from promodeler import KERNEL_VERSION
        from promodeler.core.diagnostics import ModelingError
        from promodeler.kernel import compile as compiler, export, render, report as reporting

        with open(recipe_path, "r", encoding="utf-8") as f:
            recipe = json.load(f)
        compiler.reset_scene()
        scene = compiler.compile_recipe(recipe)
        report.update(reporting.build_report(scene, recipe))
        renders_dir = os.path.join(out_dir, "renders")
        os.makedirs(renders_dir, exist_ok=True)
        report["renders"] = render.render_views(scene, recipe["render"], renders_dir)
        report["export"] = export.export_gltf(scene, os.path.join(out_dir, "model.glb"))
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
