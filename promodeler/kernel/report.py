"""Numerical QA over the evaluated (modifier-applied) geometry."""

from __future__ import annotations

import bmesh
import bpy
from mathutils import Vector

from . import space
from .compile import CompiledScene


def world_bounds(scene: CompiledScene) -> tuple[Vector, Vector] | None:
    depsgraph = bpy.context.evaluated_depsgraph_get()
    lo = Vector((float("inf"),) * 3)
    hi = Vector((float("-inf"),) * 3)
    found = False
    for obj in scene.parts.values():
        evaluated = obj.evaluated_get(depsgraph)
        for corner in evaluated.bound_box:
            p = evaluated.matrix_world @ Vector(corner)
            lo = Vector(map(min, lo, p))
            hi = Vector(map(max, hi, p))
            found = True
    return (lo, hi) if found else None


def part_statistics(obj: bpy.types.Object, depsgraph) -> dict:
    evaluated = obj.evaluated_get(depsgraph)
    mesh = evaluated.to_mesh()
    try:
        mesh.calc_loop_triangles()
        bm = bmesh.new()
        bm.from_mesh(mesh)
        non_manifold = sum(1 for e in bm.edges if not e.is_manifold)
        boundary = sum(1 for e in bm.edges if e.is_boundary)
        loose_verts = sum(1 for v in bm.verts if not v.link_edges)
        bm.free()
        return {
            "vertices": len(mesh.vertices),
            "faces": len(mesh.polygons),
            "triangles": len(mesh.loop_triangles),
            "non_manifold_edges": non_manifold,
            "boundary_edges": boundary,
            "loose_vertices": loose_verts,
            "material_slots": [m.name if m else None for m in mesh.materials],
        }
    finally:
        evaluated.to_mesh_clear()


def build_report(scene: CompiledScene, recipe: dict) -> dict:
    depsgraph = bpy.context.evaluated_depsgraph_get()
    parts = {part_id: part_statistics(obj, depsgraph) for part_id, obj in scene.parts.items()}
    totals = {
        key: sum(p[key] for p in parts.values())
        for key in ("vertices", "faces", "triangles", "non_manifold_edges", "boundary_edges", "loose_vertices")
    }
    bounds = world_bounds(scene)
    if bounds is not None:
        lo, hi = bounds
        corners = [
            space.blender_point_to_author(Vector((x, y, z)))
            for x in (lo.x, hi.x) for y in (lo.y, hi.y) for z in (lo.z, hi.z)
        ]
        author_lo = [min(c[i] for c in corners) for i in range(3)]
        author_hi = [max(c[i] for c in corners) for i in range(3)]
    else:
        author_lo = author_hi = None
    warnings = []
    max_triangles = ((recipe.get("input") or {}).get("quality") or {}).get("max_triangles")
    if max_triangles is not None and totals["triangles"] > max_triangles:
        warnings.append({"code": "budget.triangles", "message": f"{totals['triangles']} triangles exceed the budget of {max_triangles}."})
    for part_id, stats in parts.items():
        if stats["non_manifold_edges"]:
            warnings.append({"code": "geometry.nonManifold", "message": f"Part {part_id!r} has {stats['non_manifold_edges']} non-manifold edges."})
    return {
        "asset": recipe["asset"]["name"],
        "bounds": None if author_lo is None else {"min": author_lo, "max": author_hi, "space": "authoring (Y up)"},
        "totals": totals,
        "parts": parts,
        "warnings": warnings,
    }
