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

FIT_VERSION = 2
DEFAULT_ASSETS = Path(__file__).resolve().parent.parent.parent / "external" / "mhr"

# Blueprint landmark heights as fractions of standing height (05-woman cross sections).
LANDMARKS = {"hip": 0.95 / 1.6, "waist": 1.06 / 1.6, "underbust": 1.18 / 1.6, "bust": 1.25 / 1.6}
SCALE_PARAMS = (
    "scale_spine_length", "scale_neck_length", "scale_shoulder_width", "scale_uparms", "scale_lowarms",
    "scale_hip_width", "scale_hip_height", "scale_hip_depth", "scale_uplegs", "scale_lowlegs",
    "scale_ankle_height", "scale_foot_length",
)
DEFAULT_WEIGHTS = {
    "height": 40.0, "inseam": 10.0, "shoulder_width": 6.0, "foot_length": 4.0, "head_height": 2.0,
    "bust": 8.0, "underbust": 6.0, "waist": 8.0, "hip": 8.0,
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

    # --- evaluation ---------------------------------------------------------------------

    def forward(self, identity, parameters):
        """Vertices [V, 3] and joint positions [J, 3] in meters (hips anchored, not yet grounded)."""
        face = self.torch.zeros(1, 72)
        vertices, skeleton = self.model(identity.reshape(1, 45), parameters.reshape(1, 204), face)
        return vertices[0] / 100.0, skeleton[0][:, :3] / 100.0

    def joint(self, joints, name: str):
        return joints[self.bones_index(name) + 1]

    def bones_index(self, name: str) -> int:
        for index, bone in enumerate(self.bones):
            if bone["name"] == name:
                return index
        raise KeyError(name)

    # --- differentiable measurements ------------------------------------------------------

    def slice_perimeter(self, vertices, y: float, x_limit: float = 0.3):
        """Length of the torso outline where the horizontal plane at ``y`` cuts the mesh."""
        torch = self.torch
        a = vertices[self.torso_edges[:, 0]]
        b = vertices[self.torso_edges[:, 1]]
        crossing = ((a[:, 1] - y) * (b[:, 1] - y) < 0)
        a, b = a[crossing], b[crossing]
        t = ((y - a[:, 1]) / (b[:, 1] - a[:, 1])).unsqueeze(1)
        points = a + t * (b - a)
        torso = points[:, 0].abs() < x_limit
        points = points[torso][:, [0, 2]]
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
        shoulder_width = (self.joint(joints, "l_uparm") - self.joint(joints, "r_uparm")).norm()
        head_height = (y.max() - self.joint(joints, "c_head")[1]) + 0.03
        out = {"height": height, "inseam": inseam, "foot_length": foot_length, "shoulder_width": shoulder_width,
               "head_height": head_height}
        for name, fraction in LANDMARKS.items():
            out[name] = self.slice_perimeter(vertices, float((floor + fraction * height).detach()))
        return out

    # --- fitting ------------------------------------------------------------------------

    SKELETAL = ("height", "inseam", "shoulder_width", "foot_length", "head_height")
    SURFACE = ("bust", "underbust", "waist", "hip")

    def fit(self, targets: dict, iterations: int = 500, weights: dict | None = None, log=None) -> Body:
        """Three stages: skeletal scales for lengths, identity for girths, then a joint refinement."""
        torch = self.torch
        weights = {**DEFAULT_WEIGHTS, **(weights or {})}
        identity = torch.zeros(45, requires_grad=True)
        scales = torch.zeros(len(SCALE_PARAMS), requires_grad=True)
        scale_idx = torch.tensor([self.param_index[n] for n in SCALE_PARAMS])
        body_mask = torch.zeros(45)
        body_mask[:20] = 1.0
        started = time.perf_counter()

        def evaluate():
            parameters = torch.zeros(204).index_add(0, scale_idx, scales)
            vertices, joints = self.forward(identity * body_mask, parameters)
            return vertices, joints, self.measure(vertices, joints)

        def loss_for(measured, names):
            loss = torch.tensor(0.0)
            for name in names:
                target = targets.get(name)
                if target and name in measured:
                    loss = loss + weights.get(name, 1.0) * ((measured[name] - target) / target) ** 2
            return loss

        # Alternate: scales set the lengths, identity sets the girths, then both are re-tightened.
        # Joint optimisation of both sets diverged (perimeter gradients swamp the length terms).
        share = (0.25, 0.4, 0.15, 0.2)
        steps = [int(iterations * f) for f in share]
        stages = (
            ("skeleton", [scales], self.SKELETAL, 0.05, steps[0]),
            ("surface", [identity], self.SURFACE, 0.04, steps[1]),
            ("skeleton", [scales], self.SKELETAL, 0.02, steps[2]),
            ("surface", [identity], self.SURFACE, 0.015, steps[3]),
        )
        for stage_name, variables, names, lr, count in stages:
            optimizer = torch.optim.Adam(variables, lr=lr)
            for step in range(count):
                optimizer.zero_grad()
                _, _, measured = evaluate()
                loss = loss_for(measured, names) + 0.003 * (identity * body_mask).pow(2).sum() + 0.01 * scales.pow(2).sum()
                loss.backward()
                optimizer.step()
                with torch.no_grad():
                    identity.clamp_(-3.5, 3.5)
                    scales.clamp_(-2.5, 2.5)
                if log and (step % 50 == 0 or step == count - 1):
                    log(f"{stage_name:8s} step {step:3d} loss {float(loss.detach()):.5f} "
                        + " ".join(f"{k}={float(v):.3f}" for k, v in measured.items() if k in names))
        with torch.no_grad():
            parameters = torch.zeros(204).index_add(0, scale_idx, scales)
            vertices, joints, measured_t = evaluate()
            measured = {k: float(v) for k, v in measured_t.items()}
            floor = float(vertices[:, 1].min())
            vertices = vertices.clone()
            joints = joints.clone()
            vertices[:, 1] -= floor
            joints[:, 1] -= floor
        measured["fit_seconds"] = round(time.perf_counter() - started, 1)
        return Body(vertices.numpy(), joints.numpy(), (identity * body_mask).detach().numpy(), parameters.detach().numpy(), measured)

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
                                        "identity": body.identity.tolist(), "parameters": body.parameters.tolist()},
                                       ensure_ascii=False, indent=1), encoding="utf-8")
        return {"mesh": str(mesh_path), "rig": str(rig_path), "measurements": body.measurements}


def fitted_body(targets: dict, out_root: str | Path = "build/human", name: str = "body", log=None) -> dict:
    """Fit once per (targets, version) and cache the exported files under ``out_root/<name>-<hash>``."""
    digest = hashlib.sha256(json.dumps({"targets": targets, "version": FIT_VERSION}, sort_keys=True).encode()).hexdigest()[:12]
    out_dir = Path(out_root) / f"{name}-{digest}"
    marker = out_dir / "rig.json"
    if marker.is_file() and (out_dir / "body.npz").is_file():
        info = json.loads(marker.read_text(encoding="utf-8"))
        return {"mesh": str(out_dir / "body.npz"), "rig": str(marker), "measurements": info.get("measurements", {}), "cached": True}
    model = MHRModel()
    body = model.fit(targets, log=log)
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
    return {k: v for k, v in targets.items() if v}
