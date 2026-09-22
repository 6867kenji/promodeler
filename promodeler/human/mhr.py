"""Fit Meta's Momentum Human Rig (MHR) to blueprint body measurements and export it for promodeler.

MHR (https://github.com/facebookresearch/MHR, Apache 2.0) separates the
skeleton from the surface: 204 model parameters hold joint angles and
named skeletal scales (spine length, leg lengths, shoulder width, ...),
45 identity coefficients deform the surface (first 20 body, then 20 head,
5 hands). Its TorchScript export runs on the CPU at about 0.1 s per body,
outputs 18,439 vertices for LOD 1 and 127 joint transforms in
centimeters, Y up, T-pose, hips anchored at the origin.

This module needs the assets folder (``mhr_model.pt`` plus the topology,
weights and bone hierarchy dumped from ``lod1.fbx`` by
``tools/mhr_dump_lod1.py``) and the ``torch`` package. It fits the
body scales and identity coefficients to target measurements with
gradient descent and writes a mesh file and a rig file that the asset
code loads through ``MeshFile`` and ``rig_from_file``.

Units here are meters unless a name says otherwise.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from ..core import Joint, Rig
from ..core.diagnostics import ModelingError

FIT_VERSION = 18
DEFAULT_ASSETS = Path(__file__).resolve().parent.parent.parent / "external" / "mhr"

# Blueprint landmark heights as fractions of standing height (05-woman cross sections).
LANDMARKS = {"hip": 0.95 / 1.6, "waist": 1.06 / 1.6, "underbust": 1.18 / 1.6, "bust": 1.25 / 1.6}
# Landmarks measured for width/depth only (no circumference target in the blueprint).
EXTENT_LANDMARKS = {**LANDMARKS, "shoulders": 1.34 / 1.6, "neck": 1.405 / 1.6, "head": 1.49 / 1.6}
SCALE_PARAMS = (
    "scale_spine_length", "scale_neck_length", "scale_shoulder_width", "scale_uparms", "scale_lowarms",
    "scale_hip_width", "scale_hip_height", "scale_hip_depth", "scale_uplegs", "scale_lowlegs",
    "scale_ankle_height", "scale_foot_length",
)
DEFAULT_WEIGHTS = {
    "height": 80.0, "inseam": 30.0, "shoulder_width": 6.0, "foot_length": 4.0, "head_height": 2.0,
    "bust": 12.0, "underbust": 8.0, "waist": 12.0, "hip": 12.0,
}
# Section width/depth targets. Where the blueprint also gives a circumference the two cannot both hold
# (an ellipse of the 05-woman hip section is 9 cm short of its circumference); even a 0.3 weight on the
# torso extents cost 2-3 cm of circumference, so torso extents are measured and reported but not fitted.
# Neck and head have no circumference and are fitted on extents alone.
# Bust and waist extents agree with their circumferences (ellipse perimeters 0.88 and 0.60 m against 0.90
# and 0.59), so they are fitted; underbust is 3 cm off and gets a light weight; hip (0.78 vs 0.87) and the
# shoulder slice (covered by shoulder_width) are reported only.
EXTENT_WEIGHTS = {"hip": 0.0, "waist": 2.0, "underbust": 1.0, "bust": 3.0, "shoulders": 0.0, "neck": 0.0, "head": 8.0}
EXTENT_WEIGHTS_BY_NAME = {"bust_depth": 4.0}  # the flat-chest failure mode is depth, so depth leads width
BUST_LIFT = (0.0, -0.25, 1.0)  # direction of the geometric bust correction (forward, slightly down)


# MHR face expression parameters (72), identified by probing the vertex displacement they produce on the
# default body: eyelids, jaw, mouth corners and lip protrusion. Values are the coefficient per parameter.
# Blink lids need about 1.5x the unit displacement to meet; vowels are ARKit-style mixes of the basics.
FACE_SHAPES = {
    "blink_l": {14: 2.2, 12: 0.8},
    "blink_r": {15: 2.2, 13: 0.8},
    "jaw_open": {24: 1.0},
    "smile": {32: 1.0, 33: 1.0},
    "mouth_wide": {42: 1.0, 43: 1.0},
    "pucker": {40: 1.0, 41: 1.0, 27: 1.0},
    "vowel_a": {24: 0.9},
    "vowel_i": {42: 0.8, 43: 0.8, 24: 0.15},
    "vowel_u": {40: 1.0, 41: 1.0, 27: 1.0, 24: 0.2},
    "vowel_e": {24: 0.45, 42: 0.5, 43: 0.5},
    "vowel_o": {24: 0.55, 40: 0.7, 41: 0.7},
}


def assets_dir() -> Path:
    return Path(os.environ.get("PROMODELER_MHR_ASSETS", DEFAULT_ASSETS))


def assets_available(folder: Path | None = None) -> bool:
    folder = folder or assets_dir()
    return all((folder / p).is_file() for p in ("assets/mhr_model.pt", "cache/lod1_topology.npz", "cache/lod1_rig.json",
                                                "assets/compact_v6_1.model"))


def parameter_names(model_definition: Path | str) -> list[str]:
    """Model parameter order: first appearance on the right-hand sides of the ParameterTransform section."""
    names: list[str] = []
    for line in Path(model_definition).read_text(encoding="utf-8").splitlines():
        line = line.split("#")[0].strip()
        if "=" not in line or line.startswith(("[", "limit", "parameterset", "poseconstraints")):
            continue
        for token in re.findall(r"\*\s*([A-Za-z_]\w*)", line.split("=", 1)[1]):
            if token not in names:
                names.append(token)
    return names


@dataclass
class Body:
    vertices: np.ndarray  # [V, 3] meters, Y up, feet on y = 0
    joints: np.ndarray  # [J, 3] meters, same frame, index 0 is the world joint
    identity: np.ndarray  # [45]
    parameters: np.ndarray  # [204]
    measurements: dict = field(default_factory=dict)
    shape_keys: dict = field(default_factory=dict)  # name -> [V, 3] vertex deltas in meters


class MHRModel:
    """TorchScript MHR body with the LOD1 topology, weights and bone names from the FBX dump."""

    def __init__(self, folder: Path | None = None) -> None:
        import torch  # local import so the rest of promodeler never needs torch

        self.torch = torch
        self.folder = folder or assets_dir()
        if not assets_available(self.folder):
            raise ModelingError("mhr.assets", f"MHR assets are missing under {self.folder}. Download the MHR release assets there and run tools/mhr_dump_lod1.py.")
        self.model = torch.jit.load(str(self.folder / "assets" / "mhr_model.pt"), map_location="cpu").eval()
        cache = np.load(self.folder / "cache" / "lod1_topology.npz")
        self.faces = cache["faces"].astype(np.int64)
        self.uv_per_loop = cache["uv_per_loop"]
        self.loop_tris = cache["loop_tris"]
        self.weights = cache["weights"]
        rig = json.loads((self.folder / "cache" / "lod1_rig.json").read_text(encoding="utf-8"))
        self.group_names = rig["group_names"]
        self.bones = rig["bones"]  # FBX order; skeleton_state joint i + 1 corresponds to bone i
        self.param_names = parameter_names(self.folder / "assets" / "compact_v6_1.model")
        self.param_index = {n: i for i, n in enumerate(self.param_names)}
        faces = self.faces
        edges = np.concatenate([faces[:, [0, 1]], faces[:, [1, 2]], faces[:, [2, 0]]])
        edges = np.unique(np.sort(edges, axis=1), axis=0)
        self.edges = torch.from_numpy(edges)
        # Torso edges: neither end is dominated by an arm or hand group, so torso slices ignore the arms
        # even when a short spine drops the shoulders to slice height.
        dominant = self.weights.argmax(axis=1)
        arm_pattern = re.compile(r"(uparm|lowarm|wrist|pinky|ring|middle|index|thumb)")
        arm_group = np.array([bool(arm_pattern.search(n)) for n in self.group_names])
        arm_vertex = arm_group[dominant] & (self.weights.max(axis=1) > 0.0)
        torso = ~(arm_vertex[edges[:, 0]] | arm_vertex[edges[:, 1]])
        self.torso_edges = torch.from_numpy(edges[torso])
        # Landmark heights as fractions of the standing height. The module defaults are the 05-woman planes;
        # ``fit(..., landmarks=...)`` replaces them per body (a 1.76 m man's shoulders are not at 0.8375 of his height).
        self.landmarks = dict(LANDMARKS)
        self.extent_landmarks = dict(EXTENT_LANDMARKS)

    # --- evaluation ---------------------------------------------------------------------

    def forward(self, identity, parameters, face=None):
        """Vertices [V, 3] and joint positions [J, 3] in meters (hips anchored, not yet grounded)."""
        if face is None:
            face = self.torch.zeros(1, 72)
        vertices, skeleton = self.model(identity.reshape(1, 45), parameters.reshape(1, 204), face.reshape(1, 72))
        return vertices[0] / 100.0, skeleton[0][:, :3] / 100.0

    def shape_keys(self, identity, parameters, shapes: dict | None = None) -> dict:
        """Vertex deltas for each named face shape on this body (same frame as ``forward``)."""
        torch = self.torch
        with torch.no_grad():
            base, _ = self.forward(identity, parameters)
            out = {}
            for name, coefficients in (shapes or FACE_SHAPES).items():
                face = torch.zeros(72)
                for index, value in coefficients.items():
                    face[index] = value
                vertices, _ = self.forward(identity, parameters, face)
                out[name] = (vertices - base).numpy().astype(np.float32)
        return out

    def joint(self, joints, name: str):
        return joints[self.bones_index(name) + 1]

    def bones_index(self, name: str) -> int:
        for index, bone in enumerate(self.bones):
            if bone["name"] == name:
                return index
        raise KeyError(name)

    # --- differentiable measurements ------------------------------------------------------

    def slice_points(self, vertices, y: float, x_limit: float = 0.3):
        """(x, z) points where the horizontal plane at ``y`` cuts the torso/head edges (arms excluded)."""
        a = vertices[self.torso_edges[:, 0]]
        b = vertices[self.torso_edges[:, 1]]
        crossing = ((a[:, 1] - y) * (b[:, 1] - y) < 0)
        a, b = a[crossing], b[crossing]
        t = ((y - a[:, 1]) / (b[:, 1] - a[:, 1])).unsqueeze(1)
        points = a + t * (b - a)
        torso = points[:, 0].abs() < x_limit
        return points[torso][:, [0, 2]]

    def slice_extents(self, vertices, y: float, x_limit: float = 0.3):
        """(width, depth) of the slice at ``y``: x and z extents of the outline points."""
        points = self.slice_points(vertices, y, x_limit)
        if points.shape[0] < 6:
            return self.torch.tensor(0.0), self.torch.tensor(0.0)
        return points[:, 0].max() - points[:, 0].min(), points[:, 1].max() - points[:, 1].min()

    def slice_perimeter(self, vertices, y: float, x_limit: float = 0.3):
        """Length of the torso outline where the horizontal plane at ``y`` cuts the mesh."""
        torch = self.torch
        points = self.slice_points(vertices, y, x_limit)
        if points.shape[0] < 6:
            return torch.tensor(0.0)
        center = points.detach().mean(0)
        order = torch.argsort(torch.atan2(points[:, 1].detach() - center[1], points[:, 0].detach() - center[0]))
        ring = points[order]
        return (ring - ring.roll(1, 0)).norm(dim=1).sum()

    def measure(self, vertices, joints) -> dict:
        torch = self.torch
        y = vertices[:, 1]
        floor = y.min()
        height = y.max() - floor
        col = (vertices[:, 0].abs() < 0.02) & (y > floor + 0.4 * height) & (y < floor + 0.65 * height)
        inseam = (y[col].min() - floor) if bool(col.any()) else torch.tensor(0.0)
        feet = vertices[y < floor + 0.04]
        foot_length = feet[:, 2].max() - feet[:, 2].min()
        # Blueprint shoulder width is the outer (acromion) width: the torso slice at the shoulder landmark.
        # The upper-arm joint distance is reported alongside.
        joint_shoulder_width = (self.joint(joints, "l_uparm") - self.joint(joints, "r_uparm")).norm()
        shoulder_width, _ = self.slice_extents(vertices, float((floor + self.extent_landmarks["shoulders"] * height).detach()))
        head_height = (y.max() - self.joint(joints, "c_head")[1]) + 0.03
        out = {"height": height, "inseam": inseam, "foot_length": foot_length, "shoulder_width": shoulder_width,
               "joint_shoulder_width": joint_shoulder_width, "head_height": head_height}
        for name, fraction in self.landmarks.items():
            out[name] = self.slice_perimeter(vertices, float((floor + fraction * height).detach()))
        for name, fraction in self.extent_landmarks.items():
            width, depth = self.slice_extents(vertices, float((floor + fraction * height).detach()))
            out[f"{name}_width"], out[f"{name}_depth"] = width, depth
        return out

    def bust_field(self, vertices):
        """Per-vertex displacement direction for a geometric bust correction: two smooth bumps on the front
        of the chest at the bust landmark, pushing forward and slightly down. Computed from detached
        positions so only the amplitude carries gradient."""
        torch = self.torch
        v = vertices.detach()
        floor = v[:, 1].min()
        height = v[:, 1].max() - floor
        y_c = floor + self.landmarks["bust"] * height
        points = self.slice_points(v, float(y_c))
        z_c = points[:, 1].mean() if points.shape[0] else v[:, 2].mean()
        front = torch.sigmoid((v[:, 2] - z_c) / 0.015)
        scale = height / 1.6
        weight = torch.zeros(v.shape[0])
        for sx in (-0.07, 0.07):
            d2 = ((v[:, 0] - sx * scale) / (0.07 * scale)) ** 2 + ((v[:, 1] - y_c + 0.012 * scale) / (0.065 * scale)) ** 2
            weight = weight + torch.exp(-0.5 * d2)
        weight = weight * front
        direction = torch.tensor(BUST_LIFT)
        direction = direction / direction.norm()
        return weight.unsqueeze(1) * direction

    # --- fitting ------------------------------------------------------------------------

    SKELETAL = ("height", "inseam", "shoulder_width", "foot_length", "head_height")
    # inseam is in the surface set too: identity coefficients move the crotch.
    SURFACE = ("bust", "underbust", "waist", "hip", "inseam") + tuple(
        f"{name}_{axis}" for name in ("hip", "waist", "underbust", "bust", "shoulders") for axis in ("width", "depth"))
    # Head coefficients only shape the skull: neck extents and head height are body/skeleton matters and
    # chasing them with head coefficients drove them to the clamps (distorted jaw, pencil neck).
    HEAD = ("head_width", "head_depth")

    def fit(self, targets: dict, iterations: int = 800, weights: dict | None = None, log=None,
            landmarks: dict | None = None) -> Body:
        """Three stages: skeletal scales for lengths, identity for girths, then a joint refinement.

        ``landmarks`` maps ``bust/underbust/waist/hip/shoulders/neck/head`` to fractions of the standing
        height and overrides the 05-woman defaults for the planes it names.
        """
        torch = self.torch
        weights = {**DEFAULT_WEIGHTS, **(weights or {})}
        self.landmarks = {**LANDMARKS, **{k: v for k, v in (landmarks or {}).items() if k in LANDMARKS}}
        self.extent_landmarks = {**EXTENT_LANDMARKS, **{k: v for k, v in (landmarks or {}).items() if k in EXTENT_LANDMARKS}}
        body_coeffs = torch.zeros(20, requires_grad=True)  # identity[0:20]: body surface
        head_coeffs = torch.zeros(20, requires_grad=True)  # identity[20:40]: head surface
        hands = torch.zeros(5)  # identity[40:45] stay at the mean
        scales = torch.zeros(len(SCALE_PARAMS), requires_grad=True)
        # MHR's 20 body coefficients cannot give a slender body a deep bust (they widen the chest instead),
        # so a geometric bust amplitude (meters) is fitted alongside them.
        bust_amp = torch.zeros(1, requires_grad=True)
        scale_idx = torch.tensor([self.param_index[n] for n in SCALE_PARAMS])
        started = time.perf_counter()

        def identity_vector():
            return torch.cat([body_coeffs, head_coeffs, hands])

        def surface(vertices):
            return vertices + bust_amp * self.bust_field(vertices)

        def evaluate():
            parameters = torch.zeros(204).index_add(0, scale_idx, scales)
            vertices, joints = self.forward(identity_vector(), parameters)
            vertices = surface(vertices)
            return vertices, joints, self.measure(vertices, joints)

        def loss_for(measured, names):
            loss = torch.tensor(0.0)
            for name in names:
                target = targets.get(name)
                if target and name in measured:
                    default = EXTENT_WEIGHTS_BY_NAME.get(name, EXTENT_WEIGHTS.get(name.rsplit("_", 1)[0], 1.0))
                    weight = weights.get(name, default)
                    if weight:
                        loss = loss + weight * ((measured[name] - target) / target) ** 2
            return loss

        # Alternate: scales set the lengths, identity sets the girths, then both are re-tightened.
        # Joint optimisation of both sets diverged (perimeter gradients swamp the length terms).
        # Body coefficients also move the neck and head, so head targets get their own coefficients and
        # stage; otherwise a thicker neck is bought with torso circumference.
        share = (0.2, 0.25, 0.1, 0.1, 0.15, 0.08, 0.12)
        steps = [int(iterations * f) for f in share]
        # Skeleton stages after the surface stage may only move length scales: the hip and shoulder scales
        # change circumferences, drifted them 3 cm under a lengths-only loss, and diverged under a girth loss.
        girth_scales = torch.tensor([SCALE_PARAMS.index(n) for n in ("scale_shoulder_width", "scale_hip_width", "scale_hip_depth")])
        stages = (
            ("skeleton", [scales], self.SKELETAL, 0.05, steps[0], False),
            ("surface", [body_coeffs, bust_amp], self.SURFACE, 0.04, steps[1], False),
            ("head", [head_coeffs], self.HEAD, 0.04, steps[2], False),
            ("skeleton", [scales], self.SKELETAL, 0.02, steps[3], True),
            ("surface", [body_coeffs, bust_amp], self.SURFACE, 0.015, steps[4], False),
            ("skeleton", [scales], self.SKELETAL, 0.01, steps[5], True),  # identity moves the crotch
            # Girths last: the blueprint measures them at absolute heights, and any change of the limb and
            # spine proportions moves the anatomy under those planes.
            ("surface", [body_coeffs, bust_amp], self.SURFACE, 0.01, steps[6], False),
        )
        # No length stage after this: even a gentle one shifts the anatomy under the absolute-height girth
        # planes by centimeters (underbust drifted +6 cm at lr 0.004). Inseam is held by the surface stage.
        for stage_name, variables, names, lr, count, lengths_only in stages:
            groups = [{"params": [v], "lr": lr * (0.05 if v is bust_amp else 1.0)} for v in variables]
            optimizer = torch.optim.Adam(groups)
            for step in range(count):
                optimizer.zero_grad()
                _, _, measured = evaluate()
                loss = (loss_for(measured, names) + 0.003 * body_coeffs.pow(2).sum() + 0.02 * head_coeffs.pow(2).sum()
                        + 0.01 * scales.pow(2).sum() + 0.5 * bust_amp.pow(2).sum())
                loss.backward()
                if lengths_only and scales.grad is not None:
                    scales.grad[girth_scales] = 0.0
                optimizer.step()
                with torch.no_grad():
                    body_coeffs.clamp_(-3.5, 3.5)
                    head_coeffs.clamp_(-2.0, 2.0)
                    scales.clamp_(-2.5, 2.5)
                    bust_amp.clamp_(0.0, 0.08)
                if log and (step % 50 == 0 or step == count - 1):
                    log(f"{stage_name:8s} step {step:3d} loss {float(loss.detach()):.5f} "
                        + " ".join(f"{k}={float(v):.3f}" for k, v in measured.items() if k in names))
        with torch.no_grad():
            parameters = torch.zeros(204).index_add(0, scale_idx, scales)
            vertices, joints, measured_t = evaluate()
            measured = {k: float(v) for k, v in measured_t.items()}
            measured["bust_bump_m"] = float(bust_amp)
            floor = float(vertices[:, 1].min())
            vertices = vertices.clone()
            joints = joints.clone()
            vertices[:, 1] -= floor
            joints[:, 1] -= floor
        measured["fit_seconds"] = round(time.perf_counter() - started, 1)
        identity_final = identity_vector().detach()
        shape_keys = self.shape_keys(identity_final, parameters.detach())
        return Body(vertices.numpy(), joints.numpy(), identity_final.numpy(), parameters.detach().numpy(), measured, shape_keys)

    # --- export -------------------------------------------------------------------------

    def export(self, body: Body, out_dir: Path) -> dict:
        """Write ``body.npz`` (mesh, UVs, skin weights) and ``rig.json`` (joint tree in meters)."""
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        mesh_path = out_dir / "body.npz"
        np.savez_compressed(
            mesh_path, vertices=body.vertices.astype(np.float32), faces=self.faces.astype(np.int32),
            uv_per_loop=self.uv_per_loop, loop_tris=self.loop_tris, weights=self.weights,
            group_names=np.array(self.group_names),
            shape_names=np.array(list(body.shape_keys)),
            **{f"shape:{name}": deltas for name, deltas in body.shape_keys.items()},
        )
        joints = []
        heads = {bone["name"]: body.joints[i + 1] for i, bone in enumerate(self.bones)}
        children: dict[str, list[str]] = {}
        for bone in self.bones:
            if bone["parent"]:
                children.setdefault(bone["parent"], []).append(bone["name"])
        for bone in self.bones:
            head = heads[bone["name"]]
            kids = children.get(bone["name"], [])
            if kids:
                tail = np.mean([heads[k] for k in kids], axis=0)
                if np.linalg.norm(tail - head) < 1e-4:
                    tail = head + np.array([0.0, 0.03, 0.0])
            else:
                tail = head + np.array([0.0, 0.03, 0.0]) if not bone["parent"] else head + (head - heads[bone["parent"]]) * 0.5
                if np.linalg.norm(tail - head) < 1e-4:
                    tail = head + np.array([0.0, 0.03, 0.0])
            joints.append({"id": bone["name"], "parent": bone["parent"], "head": [float(c) for c in head], "tail": [float(c) for c in tail]})
        rig_path = out_dir / "rig.json"
        rig_path.write_text(json.dumps({"id": "mhr", "joints": joints, "measurements": body.measurements,
                                        "landmarks": {**self.landmarks, **self.extent_landmarks},
                                        "identity": body.identity.tolist(), "parameters": body.parameters.tolist()},
                                       ensure_ascii=False, indent=1), encoding="utf-8")
        return {"mesh": str(mesh_path), "rig": str(rig_path), "measurements": body.measurements}


def fitted_body(targets: dict, out_root: str | Path = "build/human", name: str = "body", log=None,
                landmarks: dict | None = None) -> dict:
    """Fit once per (targets, landmarks, version) and cache the exported files under ``out_root/<name>-<hash>``.

    ``landmarks`` (fractions of the height, see ``MHRModel.fit``) is optional; omitting it keeps the 05-woman
    planes and the cache keys of earlier fits.
    """
    key = {"targets": targets, "version": FIT_VERSION}
    if landmarks:
        key["landmarks"] = landmarks
    digest = hashlib.sha256(json.dumps(key, sort_keys=True).encode()).hexdigest()[:12]
    out_dir = Path(out_root) / f"{name}-{digest}"
    marker = out_dir / "rig.json"
    if marker.is_file() and (out_dir / "body.npz").is_file():
        info = json.loads(marker.read_text(encoding="utf-8"))
        return {"mesh": str(out_dir / "body.npz"), "rig": str(marker), "measurements": info.get("measurements", {}), "cached": True}
    model = MHRModel()
    body = model.fit(targets, log=log, landmarks=landmarks)
    result = model.export(body, out_dir)
    result["cached"] = False
    return result


def rig_from_file(path: str | Path, rig_id: str = "mhr", keep: set[str] | None = None,
                  offset: tuple[float, float, float] = (0.0, 0.0, 0.0)) -> Rig:
    """Build a promodeler ``Rig`` from an exported ``rig.json``.

    ``keep`` restricts the rig to the named joints (their ancestors are
    kept as needed); by default every joint is included. ``offset`` moves
    every joint, matching a translated body part (for example lifted by a
    shoe sole).
    """
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    joints = data["joints"]
    if keep is not None:
        by_id = {j["id"]: j for j in joints}
        wanted = set()
        for name in keep:
            current = name
            while current is not None and current not in wanted:
                wanted.add(current)
                current = by_id[current]["parent"]
        joints = [j for j in joints if j["id"] in wanted]
    def shift(p):
        return (p[0] + offset[0], p[1] + offset[1], p[2] + offset[2])
    return Rig(rig_id, joints=tuple(
        Joint(j["id"], head=shift(j["head"]), tail=shift(j["tail"]), parent=j["parent"]) for j in joints))


def blueprint_targets(blueprint: dict) -> dict:
    """Targets from a japan-realistic-v1 humanoid blueprint's dimensions block."""
    dims = blueprint["dimensions"]
    circ = dims.get("body_circumferences_m", {})
    targets = {
        "height": dims["barefoot_height_m"], "inseam": dims.get("inseam_m"), "shoulder_width": dims.get("shoulder_width_m"),
        "foot_length": dims.get("foot_length_m"), "head_height": dims.get("head_height_m"),
        "bust": circ.get("bust"), "underbust": circ.get("underbust"), "waist": circ.get("waist"), "hip": circ.get("hip"),
    }
    for section in blueprint.get("cross_sections", []):
        name = section.get("landmark")
        if name in EXTENT_LANDMARKS:
            targets[f"{name}_width"] = section.get("width_m")
            targets[f"{name}_depth"] = section.get("depth_m")
    return {k: v for k, v in targets.items() if v}
