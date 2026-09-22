"""Numerical QA over the evaluated (modifier-applied) geometry."""

from __future__ import annotations

import bmesh
import bpy
from mathutils import Vector
from mathutils.bvhtree import BVHTree

from . import space
from .compile import CompiledScene

SELF_INTERSECTION_TRIANGLE_LIMIT = 200_000


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


def self_intersections(mesh: bpy.types.Mesh) -> int | None:
    """Count overlapping triangle pairs that share no vertex. ``None`` when skipped for size."""
    mesh.calc_loop_triangles()
    triangles = [tuple(t.vertices) for t in mesh.loop_triangles]
    if len(triangles) > SELF_INTERSECTION_TRIANGLE_LIMIT:
        return None
    if not triangles:
        return 0
    tree = BVHTree.FromPolygons([v.co for v in mesh.vertices], triangles, all_triangles=True, epsilon=0.0)
    count = 0
    for i, j in tree.overlap(tree):
        if i < j and not set(triangles[i]) & set(triangles[j]):
            count += 1
    return count


def part_statistics(obj: bpy.types.Object, depsgraph, skip_intersections: bool = False) -> dict:
    evaluated = obj.evaluated_get(depsgraph)
    mesh = evaluated.to_mesh()
    try:
        mesh.calc_loop_triangles()
        corners = [space.blender_point_to_author(evaluated.matrix_world @ Vector(c)) for c in evaluated.bound_box]
        part_bounds = {"min": [min(c[i] for c in corners) for i in range(3)], "max": [max(c[i] for c in corners) for i in range(3)]}
        bm = bmesh.new()
        bm.from_mesh(mesh)
        non_manifold = sum(1 for e in bm.edges if not e.is_manifold)
        boundary = sum(1 for e in bm.edges if e.is_boundary)
        loose_verts = sum(1 for v in bm.verts if not v.link_edges)
        inconsistent = 0
        for e in bm.edges:
            if len(e.link_loops) == 2:
                a, b = e.link_loops
                if a.vert == b.vert:
                    inconsistent += 1
        degenerate = sum(1 for f in bm.faces if f.calc_area() < 1e-12)
        watertight = non_manifold == 0 and boundary == 0 and len(bm.faces) > 0
        volume = bm.calc_volume(signed=True) if watertight else None
        bm.free()
        return {
            "bounds": part_bounds,
            "vertices": len(mesh.vertices),
            "faces": len(mesh.polygons),
            "triangles": len(mesh.loop_triangles),
            "non_manifold_edges": non_manifold,
            "boundary_edges": boundary,
            "loose_vertices": loose_verts,
            "inconsistent_winding_edges": inconsistent,
            "degenerate_faces": degenerate,
            "watertight": watertight,
            "volume": None if volume is None else round(volume, 9),
            "self_intersections": None if skip_intersections else self_intersections(mesh),
            "material_slots": [m.name if m else None for m in mesh.materials],
        }
    finally:
        evaluated.to_mesh_clear()


def build_report(scene: CompiledScene, recipe: dict) -> dict:
    depsgraph = bpy.context.evaluated_depsgraph_get()
    parts = {part_id: part_statistics(obj, depsgraph, skip_intersections=part_id in scene.generated)
             for part_id, obj in scene.parts.items()}
    for part_id, stats in parts.items():
        if part_id in scene.generated:
            stats["generated"] = scene.generated[part_id]
        if part_id in scene.lod_stats:
            stats["lods"] = scene.lod_stats[part_id]
        if part_id in scene.uv_stats:
            stats["uv"] = scene.uv_stats[part_id]
        if part_id in scene.textures:
            stats["textures"] = {
                channel: {k: v for k, v in meta.items() if k != "image"} for channel, meta in scene.textures[part_id].items()
            }
    totals = {
        key: sum(p[key] for p in parts.values())
        for key in ("vertices", "faces", "triangles", "non_manifold_edges", "boundary_edges", "loose_vertices",
                    "inconsistent_winding_edges", "degenerate_faces")
    }
    totals["self_intersections"] = sum(p["self_intersections"] or 0 for p in parts.values())
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
        if stats["non_manifold_edges"] and "generated" not in stats:
            warnings.append({"code": "geometry.nonManifold", "message": f"Part {part_id!r} has {stats['non_manifold_edges']} non-manifold edges."})
        if stats["inconsistent_winding_edges"]:
            warnings.append({"code": "geometry.winding", "message": f"Part {part_id!r} has {stats['inconsistent_winding_edges']} edges with inconsistent winding."})
        if stats["degenerate_faces"]:
            warnings.append({"code": "geometry.degenerate", "message": f"Part {part_id!r} has {stats['degenerate_faces']} degenerate faces."})
        if stats["self_intersections"]:
            warnings.append({"code": "geometry.selfIntersection", "message": f"Part {part_id!r} has {stats['self_intersections']} self-intersecting triangle pairs."})
        if stats["self_intersections"] is None and "generated" not in stats:
            warnings.append({"code": "geometry.selfIntersectionSkipped", "message": f"Part {part_id!r} exceeds the self-intersection check limit."})
        if "uv" in stats and stats["uv"]["coverage"] < 0.2:
            warnings.append({"code": "uv.coverage", "message": f"Part {part_id!r} uses only {stats['uv']['coverage']:.0%} of its texture atlas."})
        if stats["watertight"] and stats["volume"] is not None and stats["volume"] < 0:
            warnings.append({"code": "geometry.insideOut", "message": f"Part {part_id!r} has negative volume; its normals face inward."})
    return {
        "asset": recipe["asset"]["name"],
        "bounds": None if author_lo is None else {"min": author_lo, "max": author_hi, "space": "authoring (Y up)"},
        "totals": totals,
        "parts": parts,
        "warnings": warnings,
    }
