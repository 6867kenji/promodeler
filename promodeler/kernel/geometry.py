"""Shape builders using bmesh and the data API. No ``bpy.ops`` here."""

from __future__ import annotations

import math

import bmesh
import bpy
from mathutils import Matrix, Vector

from promodeler.core.diagnostics import ModelingError


def build_mesh(name: str, shape: dict, quality: dict) -> bpy.types.Mesh:
    kind = shape["kind"]
    bm = bmesh.new()
    try:
        if kind == "box":
            sx, sy, sz = shape["size"]
            bmesh.ops.create_cube(bm, size=1.0)
            # Authored (x, y, z) sizes: Y is up, which is Blender Z.
            bmesh.ops.scale(bm, vec=Vector((sx, sz, sy)), verts=bm.verts)
        elif kind == "plane":
            sx, sz = shape["size"]
            bmesh.ops.create_grid(bm, x_segments=1, y_segments=1, size=0.5)
            bmesh.ops.scale(bm, vec=Vector((sx, sz, 1.0)), verts=bm.verts)
        elif kind == "cylinder":
            segments = shape["segments"] or quality["curve_segments"]
            bmesh.ops.create_cone(
                bm, cap_ends=True, cap_tris=False, segments=segments,
                radius1=shape["radius"], radius2=shape["radius"], depth=shape["height"],
            )
        elif kind == "cone":
            segments = shape["segments"] or quality["curve_segments"]
            bmesh.ops.create_cone(
                bm, cap_ends=True, cap_tris=False, segments=segments,
                radius1=shape["radius"], radius2=shape["top_radius"], depth=shape["height"],
            )
        elif kind == "sphere":
            segments = shape["segments"] or quality["curve_segments"]
            rings = shape["rings"] or max(quality["surface_segments"], 2)
            bmesh.ops.create_uvsphere(bm, u_segments=segments, v_segments=rings, radius=shape["radius"])
        else:
            raise ModelingError("shape.kind", f"Unknown shape kind {kind!r}.")
        if len(bm.verts) == 0 or len(bm.faces) == 0:
            raise ModelingError("shape.empty", f"Shape {kind!r} produced no geometry.")
        mesh = bpy.data.meshes.new(name)
        bm.to_mesh(mesh)
    finally:
        bm.free()
    mesh.update()
    return mesh


def apply_shading(mesh: bpy.types.Mesh, smooth_angle: float | None) -> None:
    """Flat shading by default; otherwise smooth faces with sharp edges above the angle.

    Uses face smooth flags plus edge sharpness, which Blender 4.1+ turns into
    split normals without an auto-smooth toggle.
    """
    if smooth_angle is None:
        mesh.polygons.foreach_set("use_smooth", [False] * len(mesh.polygons))
        return
    mesh.polygons.foreach_set("use_smooth", [True] * len(mesh.polygons))
    bm = bmesh.new()
    bm.from_mesh(mesh)
    sharp = []
    for edge in bm.edges:
        if len(edge.link_faces) == 2:
            angle = edge.calc_face_angle(None)
            sharp.append(angle is not None and angle > smooth_angle)
        else:
            sharp.append(False)
    bm.free()
    attr = mesh.attributes.get("sharp_edge") or mesh.attributes.new("sharp_edge", "BOOLEAN", "EDGE")
    attr.data.foreach_set("value", sharp)
    mesh.update()


def add_modifiers(obj: bpy.types.Object, modifiers: list[dict]) -> None:
    for index, spec in enumerate(modifiers):
        kind = spec["kind"]
        name = f"{kind}_{index}"
        if kind == "bevel":
            mod = obj.modifiers.new(name, "BEVEL")
            mod.width = spec["width"]
            mod.segments = spec["segments"]
            mod.limit_method = "ANGLE"
            mod.angle_limit = spec["angle_limit"]
            mod.harden_normals = True
        elif kind == "subdivision":
            mod = obj.modifiers.new(name, "SUBSURF")
            mod.levels = spec["levels"]
            mod.render_levels = spec["levels"]
        elif kind == "solidify":
            mod = obj.modifiers.new(name, "SOLIDIFY")
            mod.thickness = spec["thickness"]
            mod.offset = spec["offset"]
        else:
            raise ModelingError("modifier.kind", f"Unknown modifier kind {kind!r}.")
        if mod is None:
            raise ModelingError("modifier.create", f"Blender refused to add modifier {kind!r} to {obj.name!r}.")
