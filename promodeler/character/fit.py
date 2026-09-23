"""Garment fitting between bodies (docs/03 18.13): move a garment cut for body A onto body B.

Both bodies are described by *profiles* (``character/profiles/<race>.json`` from ``character profile``, or
``profile_from_mesh`` for an external body such as the MakeHuman base mesh): torso outlines by height, arm and leg
cross-sections along the limb axes, and the joint positions. A garment vertex is expressed in body-relative
coordinates - which segment it hangs on (torso, an arm, a leg), how far along it, the azimuth around the segment
axis and the **radial offset from the body surface** - and rebuilt on the target body with the same offset. The
ease of the garment is therefore preserved in metres while the body underneath changes; segments blend across the
armholes and the crotch so sleeves and legs do not tear away from the torso.

This is the MakeHuman "mhclo" idea (clothes as offsets from a body) generalised to two different meshes through
profiles instead of shared topology. Precision is that of the convex-hull outlines: fine for shirts, jackets,
trousers and skirts; not for gloves or anything that follows a concavity closely.
"""

from __future__ import annotations

import json
import math
import struct
from dataclasses import dataclass
from pathlib import Path

from ..core.diagnostics import ModelingError

try:  # numpy is an optional dependency of promodeler; the fitter needs it
    import numpy as np
except ImportError:  # pragma: no cover
    np = None

PROFILE_SCHEMA = "promodeler-race-profile/1.0"


def _require_numpy():
    if np is None:
        raise ModelingError("fit.numpy", "garment fitting needs numpy (pip install promodeler[all]).")


# --- mesh IO --------------------------------------------------------------------------------------

@dataclass
class Mesh:
    vertices: "np.ndarray"   # (n, 3) float
    faces: "np.ndarray"      # (m, 3) int
    normals: "np.ndarray | None" = None
    color: tuple[float, float, float, float] = (0.9, 0.9, 0.9, 1.0)
    name: str = "garment"


_COMPONENT = {5120: ("b", 1), 5121: ("B", 1), 5122: ("h", 2), 5123: ("H", 2), 5125: ("I", 4), 5126: ("f", 4)}
_COUNT = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4}


def read_glb(path: str | Path) -> Mesh:
    """All triangle primitives of a .glb (glTF 2.0 binary) as one mesh, in glTF space (metres, Y up)."""
    _require_numpy()
    data = Path(path).read_bytes()
    if data[:4] != b"glTF":
        raise ModelingError("fit.glb", f"{path} is not a binary glTF file.")
    length = struct.unpack_from("<I", data, 8)[0]
    offset = 12
    doc = None
    binary = b""
    while offset < length:
        chunk_length, chunk_type = struct.unpack_from("<II", data, offset)
        chunk = data[offset + 8: offset + 8 + chunk_length]
        if chunk_type == 0x4E4F534A:
            doc = json.loads(chunk.decode("utf-8"))
        elif chunk_type == 0x004E4942:
            binary = chunk
        offset += 8 + chunk_length
    if doc is None:
        raise ModelingError("fit.glb", f"{path} has no JSON chunk.")

    def accessor(index: int):
        acc = doc["accessors"][index]
        view = doc["bufferViews"][acc["bufferView"]]
        fmt, size = _COMPONENT[acc["componentType"]]
        count = _COUNT[acc["type"]]
        start = view.get("byteOffset", 0) + acc.get("byteOffset", 0)
        stride = view.get("byteStride", size * count)
        out = np.empty((acc["count"], count), dtype=np.float64 if fmt == "f" else np.int64)
        for i in range(acc["count"]):
            out[i] = struct.unpack_from("<" + fmt * count, binary, start + i * stride)
        return out

    vertices, normals, faces = [], [], []
    base = 0
    has_normals = True
    for node in doc.get("nodes", []):
        pass  # node transforms are applied by exporters we control (promodeler writes world-space parts); ignored here
    for mesh in doc.get("meshes", []):
        for prim in mesh.get("primitives", []):
            if prim.get("mode", 4) != 4:
                continue
            pos = accessor(prim["attributes"]["POSITION"])
            vertices.append(pos)
            if "NORMAL" in prim["attributes"]:
                normals.append(accessor(prim["attributes"]["NORMAL"]))
            else:
                has_normals = False
            idx = accessor(prim["indices"]).reshape(-1) if "indices" in prim else np.arange(len(pos))
            faces.append(idx.reshape(-1, 3) + base)
            base += len(pos)
    if not vertices:
        raise ModelingError("fit.glb", f"{path} has no triangle primitives.")
    return Mesh(vertices=np.vstack(vertices), faces=np.vstack(faces).astype(np.int64),
                normals=np.vstack(normals) if has_normals and normals else None, name=Path(path).stem)


def read_obj(path: str | Path) -> Mesh:
    _require_numpy()
    vertices, faces = [], []
    for line in Path(path).read_text(encoding="utf-8", errors="replace").splitlines():
        parts = line.split()
        if not parts:
            continue
        if parts[0] == "v":
            vertices.append([float(parts[1]), float(parts[2]), float(parts[3])])
        elif parts[0] == "f":
            ids = [int(p.split("/")[0]) - 1 for p in parts[1:]]
            for k in range(1, len(ids) - 1):   # fan-triangulate polygons
                faces.append([ids[0], ids[k], ids[k + 1]])
    if not vertices or not faces:
        raise ModelingError("fit.obj", f"{path} has no vertices or faces.")
    return Mesh(vertices=np.array(vertices, dtype=np.float64), faces=np.array(faces, dtype=np.int64), name=Path(path).stem)


def read_mesh(path: str | Path) -> Mesh:
    suffix = Path(path).suffix.lower()
    if suffix == ".glb":
        return read_glb(path)
    if suffix == ".obj":
        return read_obj(path)
    raise ModelingError("fit.format", f"{path}: only .glb and .obj are read.")


def vertex_normals(vertices, faces):
    normals = np.zeros_like(vertices)
    a, b, c = vertices[faces[:, 0]], vertices[faces[:, 1]], vertices[faces[:, 2]]
    face_normals = np.cross(b - a, c - a)   # area-weighted
    for k in range(3):
        np.add.at(normals, faces[:, k], face_normals)
    lengths = np.linalg.norm(normals, axis=1, keepdims=True)
    lengths[lengths == 0] = 1.0
    return normals / lengths


def write_glb(path: str | Path, mesh: Mesh) -> None:
    """A minimal glTF 2.0 binary: one node, one mesh, one primitive, one PBR material with the mesh color."""
    _require_numpy()
    vertices = np.ascontiguousarray(mesh.vertices, dtype=np.float32)
    normals = np.ascontiguousarray(mesh.normals if mesh.normals is not None else vertex_normals(mesh.vertices, mesh.faces), dtype=np.float32)
    indices = np.ascontiguousarray(mesh.faces.reshape(-1), dtype=np.uint32)
    blobs = [vertices.tobytes(), normals.tobytes(), indices.tobytes()]
    views, offset = [], 0
    for blob in blobs:
        views.append({"buffer": 0, "byteOffset": offset, "byteLength": len(blob)})
        offset += len(blob) + (-len(blob)) % 4
    binary = b"".join(blob + b"\0" * ((-len(blob)) % 4) for blob in blobs)
    lo, hi = vertices.min(axis=0).tolist(), vertices.max(axis=0).tolist()
    doc = {
        "asset": {"version": "2.0", "generator": "promodeler fit"},
        "scene": 0, "scenes": [{"nodes": [0]}], "nodes": [{"mesh": 0, "name": mesh.name}],
        "meshes": [{"name": mesh.name, "primitives": [{"attributes": {"POSITION": 0, "NORMAL": 1}, "indices": 2, "material": 0, "mode": 4}]}],
        "materials": [{"name": mesh.name + "_material", "pbrMetallicRoughness": {"baseColorFactor": list(mesh.color), "metallicFactor": 0.0, "roughnessFactor": 0.8}, "doubleSided": True}],
        "accessors": [
            {"bufferView": 0, "componentType": 5126, "count": len(vertices), "type": "VEC3", "min": lo, "max": hi},
            {"bufferView": 1, "componentType": 5126, "count": len(normals), "type": "VEC3"},
            {"bufferView": 2, "componentType": 5125, "count": len(indices), "type": "SCALAR"},
        ],
        "bufferViews": views, "buffers": [{"byteLength": len(binary)}],
    }
    json_bytes = json.dumps(doc, separators=(",", ":")).encode("utf-8")
    json_bytes += b" " * ((-len(json_bytes)) % 4)
    total = 12 + 8 + len(json_bytes) + 8 + len(binary)
    with open(path, "wb") as f:
        f.write(b"glTF" + struct.pack("<II", 2, total))
        f.write(struct.pack("<II", len(json_bytes), 0x4E4F534A) + json_bytes)
        f.write(struct.pack("<II", len(binary), 0x004E4942) + binary)


# --- profiles ---------------------------------------------------------------------------------

class Outline:
    """A convex outline (u, v) as a polar radius function about its centroid."""

    def __init__(self, points):
        pts = np.asarray(points, dtype=np.float64)
        self.centre = pts.mean(axis=0)
        rel = pts - self.centre
        angles = np.arctan2(rel[:, 0], rel[:, 1])
        radii = np.hypot(rel[:, 0], rel[:, 1])
        order = np.argsort(angles)
        self.angles = np.concatenate([angles[order] - 2 * math.pi, angles[order], angles[order] + 2 * math.pi])
        self.radii = np.concatenate([radii[order]] * 3)

    def radius(self, theta):
        return np.interp(theta, self.angles, self.radii)


class Segment:
    """A limb or the torso: an axis with cross-section outlines at parameters along it."""

    def __init__(self, origin, direction, length, e1, e2, params, outlines):
        self.origin = np.asarray(origin, dtype=np.float64)
        self.direction = np.asarray(direction, dtype=np.float64)
        self.length = float(length)
        self.e1 = np.asarray(e1, dtype=np.float64)
        self.e2 = np.asarray(e2, dtype=np.float64)
        self.params = np.asarray(params, dtype=np.float64)   # increasing, in metres along the axis
        self.outlines = outlines

    def decompose(self, p):
        """(t, theta, radial offset) of a point: t along the axis in metres, azimuth and distance beyond the body surface."""
        rel = p - self.origin
        t = float(rel @ self.direction)
        in_plane = rel - t * self.direction
        a, b = float(in_plane @ self.e1), float(in_plane @ self.e2)
        centre = self._centre(t)
        theta = math.atan2(a - centre[0], b - centre[1])
        r_point = math.hypot(a - centre[0], b - centre[1])
        return t, theta, r_point - self._radius(t, theta)

    def compose(self, t, theta, offset):
        centre = self._centre(t)
        r = max(0.0, self._radius(t, theta) + offset)
        a = centre[0] + r * math.sin(theta)
        b = centre[1] + r * math.cos(theta)
        return self.origin + t * self.direction + a * self.e1 + b * self.e2

    def surface_radius(self, p):
        t, theta, _ = self.decompose(p)
        return self._radius(t, theta)

    def _bracket(self, t):
        t = min(max(t, self.params[0]), self.params[-1])
        j = int(np.searchsorted(self.params, t, side="right")) - 1
        j = min(max(j, 0), len(self.params) - 2) if len(self.params) > 1 else 0
        if len(self.params) == 1:
            return j, j, 0.0
        span = self.params[j + 1] - self.params[j]
        return j, j + 1, 0.0 if span <= 0 else (t - self.params[j]) / span

    def _centre(self, t):
        j0, j1, f = self._bracket(t)
        return (1 - f) * self.outlines[j0].centre + f * self.outlines[j1].centre

    def _radius(self, t, theta):
        j0, j1, f = self._bracket(t)
        return (1 - f) * self.outlines[j0].radius(theta) + f * self.outlines[j1].radius(theta)


class BodyProfile:
    """The segments of one body from a race profile JSON."""

    def __init__(self, data: dict):
        _require_numpy()
        if data.get("schema") != PROFILE_SCHEMA:
            raise ModelingError("fit.profile", f"profile schema {data.get('schema')!r} is not {PROFILE_SCHEMA}.")
        self.data = data
        bones = data["bones"]
        self.hips = np.array(bones["Hips"], dtype=np.float64)
        self.neck_y = float(data.get("neck_y", bones["Neck"][1]))
        self.height = float(data["height"])
        slices = sorted(data["torso_slices"], key=lambda s: s["y"])
        # Torso: a vertical axis at the hips' x/z, sections at their heights, e1 = +X, e2 = +Z.
        self.torso = Segment(origin=[self.hips[0], 0.0, self.hips[2]], direction=[0.0, 1.0, 0.0], length=self.neck_y, e1=[1, 0, 0], e2=[0, 0, 1],
                             params=[s["y"] for s in slices], outlines=[Outline([[p[0] - self.hips[0], p[1] - self.hips[2]] for p in s["points"]]) for s in slices])
        self.arms: dict[str, Segment] = {}
        for side, arm in (data.get("arms") or {}).items():
            if len(arm.get("slices") or []) < 2:
                continue
            angle = float(arm["angle_z"])
            self.arms[side] = Segment(origin=arm["shoulder"], direction=arm["dir"], length=arm["length"],
                                      e1=[math.cos(angle), math.sin(angle), 0.0], e2=[0.0, 0.0, 1.0],
                                      params=[s["t"] for s in arm["slices"]], outlines=[Outline(s["points"]) for s in arm["slices"]])
        self.legs: dict[str, Segment] = {}
        for side, leg in (data.get("legs") or {}).items():
            if len(leg.get("slices") or []) < 2:
                continue
            self.legs[side] = Segment(origin=leg["hip"], direction=leg["dir"], length=leg["length"], e1=leg["e1"], e2=leg["e2"],
                                      params=[s["t"] for s in leg["slices"]], outlines=[Outline(s["points"]) for s in leg["slices"]])

    @classmethod
    def load(cls, path: str | Path) -> "BodyProfile":
        return cls(json.loads(Path(path).read_text(encoding="utf-8")))


# --- fitting ----------------------------------------------------------------------------------

def _smooth(x: float) -> float:
    x = min(1.0, max(0.0, x))
    return x * x * (3 - 2 * x)


def segment_weights(profile: BodyProfile, p) -> dict[str, float]:
    """How much a point belongs to each limb (0..1); the torso takes the rest."""
    weights: dict[str, float] = {}
    for side, arm in profile.arms.items():
        rel = p - arm.origin
        t = float(rel @ arm.direction)
        if t < -0.10 or t > arm.length * 1.2:
            continue
        radial = float(np.linalg.norm(rel - t * arm.direction))
        surface = arm.surface_radius(p) if t >= 0 else arm.outlines[0].radius(0.0)
        if radial > surface + 0.15:
            continue
        # Blend in over the shoulder: fully arm once the point is 6 cm outboard of the shoulder joint.
        outboard = (abs(p[0]) - abs(arm.origin[0])) / 0.08
        weights[f"arm_{side}"] = _smooth(outboard + 0.25) * _smooth((surface + 0.15 - radial) / 0.08)
    for side, leg in profile.legs.items():
        rel = p - leg.origin
        t = float(rel @ leg.direction)
        if t < -0.05 or t > leg.length * 1.15:
            continue
        radial = float(np.linalg.norm(rel - t * leg.direction))
        surface = leg.surface_radius(p) if t >= 0 else leg.outlines[0].radius(0.0)
        if radial > surface + 0.25:
            continue
        # Blend in below the hip joint: fully leg 12 cm below it.
        below = (leg.origin[1] - p[1]) / 0.12
        weights[f"leg_{side}"] = _smooth(below) * _smooth((surface + 0.25 - radial) / 0.10)
    return weights


def fit_point(p, source: BodyProfile, target: BodyProfile):
    weights = segment_weights(source, p)
    limb_total = min(1.0, sum(weights.values()))
    result = np.zeros(3)
    # Torso: normalised height between the hips and the neck, offset from the outline.
    u = (p[1] - source.hips[1]) / (source.neck_y - source.hips[1])
    t_torso_source = p[1]
    _, theta, offset = source.torso.decompose(np.array([p[0], t_torso_source, p[2]]))
    y_target = target.hips[1] + u * (target.neck_y - target.hips[1])
    torso_point = target.torso.compose(y_target, theta, offset)
    torso_point[1] = y_target
    result += (1.0 - limb_total) * torso_point
    scale = 1.0 / sum(weights.values()) if sum(weights.values()) > 1.0 else 1.0
    for key, weight in weights.items():
        kind, side = key.split("_", 1)
        seg_source = (source.arms if kind == "arm" else source.legs)[side]
        seg_target = (target.arms if kind == "arm" else target.legs).get(side)
        if seg_target is None:
            result += weight * scale * torso_point
            continue
        t, theta, offset = seg_source.decompose(p)
        t_target = t / seg_source.length * seg_target.length
        result += weight * scale * seg_target.compose(t_target, theta, offset)
    return result


def fit_mesh(mesh: Mesh, source: BodyProfile, target: BodyProfile, mirror_x: bool = False) -> Mesh:
    _require_numpy()
    vertices = mesh.vertices.copy()
    if mirror_x:
        vertices[:, 0] *= -1
    fitted = np.array([fit_point(v, source, target) for v in vertices])
    if mirror_x:
        fitted[:, 0] *= -1
    return Mesh(vertices=fitted, faces=mesh.faces.copy(), normals=vertex_normals(fitted, mesh.faces), color=mesh.color, name=mesh.name)


def fit_garment(garment: str | Path, source_profile: str | Path, target_profile: str | Path, out: str | Path, mirror_x: bool = False) -> dict:
    """Read a garment mesh, fit it from the source body to the target body and write a GLB; returns a small report."""
    mesh = read_mesh(garment)
    source = BodyProfile.load(source_profile)
    target = BodyProfile.load(target_profile)
    fitted = fit_mesh(mesh, source, target, mirror_x=mirror_x)
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    write_glb(out, fitted)
    moved = np.linalg.norm(fitted.vertices - mesh.vertices, axis=1)
    return {"garment": str(garment), "source": str(source_profile), "target": str(target_profile), "out": str(out),
            "vertices": int(len(mesh.vertices)), "triangles": int(len(mesh.faces)),
            "moved_m": {"mean": float(moved.mean()), "max": float(moved.max())},
            "bounds_min": fitted.vertices.min(axis=0).round(4).tolist(), "bounds_max": fitted.vertices.max(axis=0).round(4).tolist()}


# --- profiles from an external body mesh ------------------------------------------------------------

def _convex_hull(points):
    pts = sorted(set((float(a), float(b)) for a, b in points))
    if len(pts) < 3:
        return pts

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower, upper = [], []
    for p in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    for p in reversed(pts):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    return lower[:-1] + upper[:-1]


def _plane_cut(vertices, edges, origin, normal, keep):
    """Points where mesh edges (whose endpoints both satisfy ``keep``) cross the plane through origin with normal."""
    a = vertices[edges[:, 0]]
    b = vertices[edges[:, 1]]
    da = (a - origin) @ normal
    db = (b - origin) @ normal
    mask = (da * db < 0) & keep[edges[:, 0]] & keep[edges[:, 1]]
    t = (da[mask] / (da[mask] - db[mask]))[:, None]
    return a[mask] + t * (b[mask] - a[mask])


def profile_from_mesh(mesh: Mesh, landmarks: dict, race: str = "external", torso_step: float = 0.02, limb_step: float = 0.03) -> dict:
    """A race-profile document for an arbitrary body mesh from joint positions (Hips, Neck, Head, <Side>Arm/Hand, <Side>UpLeg/Foot).

    Without skin weights the arm and leg exclusions use geometry: torso outlines drop points outboard of the shoulder
    joints above the armpit, limb sections keep points near the limb axis on that side."""
    _require_numpy()
    v = mesh.vertices
    f = mesh.faces
    edges = np.unique(np.sort(np.vstack([f[:, [0, 1]], f[:, [1, 2]], f[:, [2, 0]]]), axis=1), axis=0)
    hips = np.array(landmarks["Hips"], dtype=np.float64)
    neck = np.array(landmarks["Neck"], dtype=np.float64)
    head = np.array(landmarks.get("Head", [neck[0], neck[1] + 0.09, neck[2]]), dtype=np.float64)
    floor, top = float(v[:, 1].min()), float(v[:, 1].max())
    height = top - floor
    shoulder_x = min(abs(landmarks[s][0]) for s in ("LeftArm", "RightArm") if s in landmarks) if any(s in landmarks for s in ("LeftArm", "RightArm")) else 0.2
    armpit_y = min(landmarks[s][1] for s in ("LeftArm", "RightArm") if s in landmarks) - 0.22 if any(s in landmarks for s in ("LeftArm", "RightArm")) else neck[1] - 0.3

    # Vertices near an arm axis (shoulder -> hand) stand in for the arm-bone weights the Unity exporter has.
    near_arm = np.zeros(len(v), dtype=bool)
    for S in ("Left", "Right"):
        if f"{S}Arm" in landmarks and f"{S}Hand" in landmarks:
            start = np.array(landmarks[f"{S}Arm"], dtype=np.float64)
            end = np.array(landmarks[f"{S}Hand"], dtype=np.float64)
            axis = end - start
            length = float(np.linalg.norm(axis))
            direction = axis / length
            rel = v - start
            t = rel @ direction
            radial = np.linalg.norm(rel - np.outer(t, direction), axis=1)
            near_arm |= (t > 0.04) & (t < length + 0.1) & (radial < 0.11)
    torso = []
    y = floor + 0.42 * height
    while y < head[1]:
        keep = ~near_arm
        if y > armpit_y:
            keep &= np.abs(v[:, 0]) < shoulder_x + 0.01   # and nothing outboard of the shoulders above the armpit line
        pts = _plane_cut(v, edges, np.array([0.0, y, 0.0]), np.array([0.0, 1.0, 0.0]), keep)
        pts = pts[np.abs(pts[:, 0]) < 0.4]
        if len(pts) >= 6:
            torso.append({"y": float(y), "points": [[float(a), float(b)] for a, b in _convex_hull(pts[:, [0, 2]])]})
        y += torso_step

    def limb(start_key, end_key, kind):
        if start_key not in landmarks or end_key not in landmarks:
            return None
        start = np.array(landmarks[start_key], dtype=np.float64)
        end = np.array(landmarks[end_key], dtype=np.float64)
        axis = end - start
        length = float(np.linalg.norm(axis))
        if kind == "arm":
            direction = np.array([axis[0], axis[1], 0.0]); direction /= np.linalg.norm(direction)
            angle = math.atan2(-direction[0], direction[1])
            e1 = np.array([math.cos(angle), math.sin(angle), 0.0]); e2 = np.array([0.0, 0.0, 1.0])
        else:
            direction = axis / length
            e1 = np.cross(np.array([0.0, 0.0, 1.0]), direction); e1 /= np.linalg.norm(e1)
            e2 = np.cross(direction, e1); e2 /= np.linalg.norm(e2)
        side_sign = -1.0 if start[0] < 0 else 1.0
        slices = []
        t = 0.0 if kind == "arm" else 0.02
        while t < length - (0.02 if kind == "arm" else 0.05):
            centre = start + direction * t
            keep = (v[:, 0] * side_sign > (abs(start[0]) - 0.03 if kind == "arm" else -0.005)) & (np.linalg.norm(v - centre, axis=1) < (0.25 if kind == "arm" else 0.3))
            if kind == "leg":
                keep &= v[:, 1] < start[1] + 0.02
            pts = _plane_cut(v, edges, centre, direction, keep)
            rel = pts - centre
            if kind == "arm":
                keep2 = np.linalg.norm(rel, axis=1) < 0.2
            else:
                keep2 = np.linalg.norm(rel, axis=1) < 0.25
            rel = rel[keep2]
            if len(rel) >= 6:
                ab = np.stack([rel @ e1, rel @ e2], axis=1)
                slices.append({"t": float(t), "center": centre.round(6).tolist(), "points": [[float(a), float(b)] for a, b in _convex_hull(ab)]})
            t += limb_step
        doc = {"dir": direction.round(6).tolist(), "length": length, "slices": slices}
        if kind == "arm":
            doc.update({"shoulder": start.tolist(), "wrist": end.tolist(), "angle_z": angle})
        else:
            doc.update({"hip": start.tolist(), "ankle": end.tolist(), "e1": e1.round(6).tolist(), "e2": e2.round(6).tolist()})
        return doc

    arms = {s: limb(f"{S}Arm", f"{S}Hand", "arm") for s, S in (("left", "Left"), ("right", "Right"))}
    legs = {s: limb(f"{S}UpLeg", f"{S}Foot", "leg") for s, S in (("left", "Left"), ("right", "Right"))}
    return {
        "schema": PROFILE_SCHEMA, "race": race, "uma_race": None, "pose": "as authored (metres, Y up, faces +Z assumed)",
        "floor": floor, "height": height, "vertices": int(len(v)), "bones": {k: list(map(float, val)) for k, val in landmarks.items()},
        "torso_slices": torso, "neck_y": float(neck[1]),
        "arms": {k: val for k, val in arms.items() if val}, "legs": {k: val for k, val in legs.items() if val},
    }
