"""UV charting for baking: angle-based projection charts packed into one atlas."""

from __future__ import annotations

import math

import bpy

from promodeler.core.diagnostics import ModelingError


def unwrap(obj: bpy.types.Object, angle_limit: float = math.radians(66.0), margin: float = 0.02) -> None:
    """Smart-project charts; when a fragmented mesh (cloth folds, hundreds of tubes) leaves the atlas
    mostly margin, redo it with a wide angle limit and a tight margin."""
    _smart_project(obj, angle_limit, margin)
    if uv_statistics(obj.data, 1)["coverage"] < 0.15:
        _smart_project(obj, math.radians(89.0), 0.001)


def _smart_project(obj: bpy.types.Object, angle_limit: float, margin: float) -> None:
    for other in bpy.context.scene.objects:
        other.select_set(False)
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.mode_set(mode="EDIT")
    try:
        bpy.ops.mesh.select_all(action="SELECT")
        result = bpy.ops.uv.smart_project(
            angle_limit=angle_limit, island_margin=margin, area_weight=0.0, correct_aspect=True, scale_to_bounds=False,
        )
    finally:
        bpy.ops.object.mode_set(mode="OBJECT")
    if "FINISHED" not in result or not obj.data.uv_layers:
        raise ModelingError("uv.unwrap", f"UV unwrap failed for {obj.name!r}.")


def uv_statistics(mesh: bpy.types.Mesh, resolution: int) -> dict:
    """Atlas coverage and texel density from triangle areas in UV and object space."""
    layer = mesh.uv_layers.active
    if layer is None:
        return {"coverage": 0.0, "texel_density_px_per_m": 0.0}
    mesh.calc_loop_triangles()
    uv = layer.uv
    uv_area = 0.0
    surface_area = 0.0
    for tri in mesh.loop_triangles:
        a, b, c = (uv[i].vector for i in tri.loops)
        uv_area += abs((b.x - a.x) * (c.y - a.y) - (c.x - a.x) * (b.y - a.y)) * 0.5
        surface_area += tri.area
    density = math.sqrt(uv_area * resolution * resolution / surface_area) if surface_area > 0 else 0.0
    return {"coverage": round(uv_area, 4), "texel_density_px_per_m": round(density, 1)}
