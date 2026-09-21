"""Shape builders using bmesh and the data API. No ``bpy.ops`` here."""

from __future__ import annotations

import bmesh
import bpy
from mathutils import Vector
from mathutils.geometry import delaunay_2d_cdt

from promodeler.core import meshgen
from promodeler.core.diagnostics import ModelingError

from . import space
from .fields import FieldCompiler

PRIMITIVE_KINDS = ("box", "plane", "cylinder", "cone", "sphere")


def build_mesh(name: str, shape: dict, quality: dict) -> bpy.types.Mesh:
    kind = shape["kind"]
    bm = bmesh.new()
    try:
        if kind in PRIMITIVE_KINDS:
            _build_primitive(bm, shape, quality)
        else:
            _build_spec(bm, meshgen.generate(shape, quality))
        if len(bm.verts) == 0 or len(bm.faces) == 0:
            raise ModelingError("shape.empty", f"Shape {kind!r} produced no geometry.")
        bm.normal_update()
        mesh = bpy.data.meshes.new(name)
        bm.to_mesh(mesh)
    finally:
        bm.free()
    mesh.update()
    return mesh


def _build_primitive(bm: bmesh.types.BMesh, shape: dict, quality: dict) -> None:
    kind = shape["kind"]
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


def _build_spec(bm: bmesh.types.BMesh, spec: meshgen.MeshSpec) -> None:
    verts = [bm.verts.new(space.A2B @ Vector(p)) for p in spec.vertices]
    bm.verts.ensure_lookup_table()
    for face in spec.faces:
        _new_face(bm, [verts[i] for i in face])
    for fill in spec.fills:
        wanted = (space.A2B @ Vector(fill.normal)).normalized()
        flat = [i for loop in fill.loops for i in loop]
        triangles = _triangulate_with_holes([[verts[i].co for i in loop] for loop in fill.loops], wanted)
        cap_faces = []
        for tri in triangles:
            a, b, c = (verts[flat[i]] for i in tri)
            normal = (b.co - a.co).cross(c.co - a.co)
            if normal.dot(wanted) < 0:
                a, b, c = a, c, b
            cap_faces.append(_new_face(bm, [a, b, c]))
        # Coplanar cap triangles are merged into quads where possible so that
        # later bevels and booleans see fewer slivers. Full n-gons with holes
        # do not exist in Blender; use a boolean cutter when a hole must keep
        # a clean n-gon cap around it.
        bmesh.ops.join_triangles(
            bm, faces=cap_faces, cmp_seam=False, cmp_sharp=False, cmp_uvs=False, cmp_vcols=False,
            cmp_materials=False, angle_face_threshold=3.14, angle_shape_threshold=3.14,
        )


def _triangulate_with_holes(loops, normal: Vector) -> list[tuple[int, int, int]]:
    """Constrained Delaunay triangulation of an outer loop minus hole loops.

    Every boundary vertex is preserved and no triangle edge passes through
    another vertex, unlike ear clipping on collinear boundaries. Indices
    refer to the concatenated loop vertices.
    """
    u = normal.orthogonal().normalized()
    v = normal.cross(u).normalized()
    coords = []
    edges = []
    hole_rings = []
    offset = 0
    for index, loop in enumerate(loops):
        ring = [(p.dot(u), p.dot(v)) for p in loop]
        coords.extend(ring)
        if index > 0:
            edges.extend((offset + i, offset + (i + 1) % len(loop)) for i in range(len(loop)))
            hole_rings.append(ring)
        offset += len(loop)
    outer_face = [list(range(len(loops[0])))]
    # Mode 1 keeps triangles inside the outer face; hole edges are hard
    # constraints, so each triangle lies fully inside or outside a hole.
    result = delaunay_2d_cdt(coords, edges, outer_face, 1, 1e-9)
    out_coords, out_faces, orig_verts = result[0], result[2], result[3]
    index_map = []
    for originals in orig_verts:
        if not originals:
            raise ModelingError("profile.fill", "Profile loops intersect; the cap could not be triangulated.")
        index_map.append(originals[0])
    triangles = []
    for face in out_faces:
        if len(face) != 3:
            raise ModelingError("profile.fill", "Triangulation returned a non-triangle face.")
        cx = sum(out_coords[i][0] for i in face) / 3
        cy = sum(out_coords[i][1] for i in face) / 3
        if any(_point_in_ring((cx, cy), ring) for ring in hole_rings):
            continue
        triangles.append(tuple(index_map[i] for i in face))
    if not triangles:
        raise ModelingError("profile.fill", "Could not triangulate a cap with holes.")
    return triangles


def _point_in_ring(point, ring) -> bool:
    x, y = point
    inside = False
    n = len(ring)
    for i in range(n):
        x0, y0 = ring[i]
        x1, y1 = ring[(i + 1) % n]
        if (y0 > y) != (y1 > y) and x < x0 + (y - y0) / (y1 - y0) * (x1 - x0):
            inside = not inside
    return inside


def _new_face(bm: bmesh.types.BMesh, face_verts):
    try:
        return bm.faces.new(face_verts)
    except ValueError as exc:
        raise ModelingError("shape.face", f"Invalid polygon in generated surface: {exc}") from None


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


AXIS_INDEX_BLENDER = {"x": 0, "y": 2, "z": 1}


def build_displace_group(name: str, height_spec: dict) -> bpy.types.NodeTree:
    """A Geometry Nodes group offsetting every vertex along its normal by a scalar field."""
    group = bpy.data.node_groups.new(name, "GeometryNodeTree")
    group.interface.new_socket(name="Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")
    group.interface.new_socket(name="Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
    group_in = group.nodes.new("NodeGroupInput")
    group_out = group.nodes.new("NodeGroupOutput")
    set_position = group.nodes.new("GeometryNodeSetPosition")
    fc = FieldCompiler(group, mode="geometry")
    height = fc.scalar(height_spec)
    offset = group.nodes.new("ShaderNodeVectorMath")
    offset.operation = "SCALE"
    group.links.new(fc.normal_socket, offset.inputs[0])
    fc._value(offset.inputs["Scale"], height)
    group.links.new(group_in.outputs[0], set_position.inputs["Geometry"])
    group.links.new(offset.outputs[0], set_position.inputs["Offset"])
    group.links.new(set_position.outputs[0], group_out.inputs[0])
    return group


def add_modifiers(obj: bpy.types.Object, modifiers: list[dict], make_cutter=None) -> None:
    """``make_cutter(index, spec)`` returns a scene object for boolean operands."""
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
            mod.subdivision_type = "CATMULL_CLARK" if spec.get("smooth", True) else "SIMPLE"
            mod.levels = spec["levels"]
            mod.render_levels = spec["levels"]
        elif kind == "displace":
            mod = obj.modifiers.new(name, "NODES")
            mod.node_group = build_displace_group(f"displace:{obj.name}:{index}", spec["height"])
        elif kind == "simple_deform":
            mod = obj.modifiers.new(name, "SIMPLE_DEFORM")
            mod.deform_method = spec["method"].upper()
            mod.deform_axis = "XZY"[AXIS_INDEX_BLENDER[spec["axis"]]] if False else ("X", "Z", "Y")[("x", "y", "z").index(spec["axis"])]
            if spec["method"] == "taper":
                mod.factor = spec["factor"]
            else:
                mod.angle = spec["angle"]
        elif kind == "solidify":
            mod = obj.modifiers.new(name, "SOLIDIFY")
            mod.thickness = spec["thickness"]
            mod.offset = spec["offset"]
        elif kind == "mirror":
            mod = obj.modifiers.new(name, "MIRROR")
            axes = [False, False, False]
            for axis in spec["axes"]:
                axes[AXIS_INDEX_BLENDER[axis]] = True
            mod.use_axis = axes
            mod.use_mirror_merge = spec["merge_distance"] > 0
            mod.merge_threshold = spec["merge_distance"]
        elif kind == "array":
            mod = obj.modifiers.new(name, "ARRAY")
            mod.count = spec["count"]
            mod.use_relative_offset = False
            mod.use_constant_offset = True
            mod.constant_offset_displace = space.A2B.to_3x3() @ Vector(spec["offset"])
            mod.use_merge_vertices = spec["merge"]
        elif kind == "boolean":
            if make_cutter is None:
                raise ModelingError("boolean.context", "Booleans are not allowed here.")
            mod = obj.modifiers.new(name, "BOOLEAN")
            mod.operation = spec["operation"].upper()
            mod.object = make_cutter(index, spec["cutter"])
            try:
                mod.solver = spec["solver"].upper()
            except TypeError:
                raise ModelingError("boolean.solver", f"This Blender lacks the {spec['solver']!r} boolean solver.") from None
        else:
            raise ModelingError("modifier.kind", f"Unknown modifier kind {kind!r}.")
        if mod is None:
            raise ModelingError("modifier.create", f"Blender refused to add modifier {kind!r} to {obj.name!r}.")
