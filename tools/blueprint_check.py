"""Compare a built humanoid asset with its japan-realistic-v1 blueprint.

    python tools/blueprint_check.py blueprints/japan-realistic-v1/05-woman/blueprint.json [build/haruka/<hash>] [--lift 0.025]

Reads the blueprint's dimensions, cross sections, part boxes and budgets, the
build's ``report.json`` (part bounds, triangle counts) and the fitted body
(``build/human/<name>-<hash>/body.npz`` and ``rig.json`` measurements), and
prints every number side by side with its difference. ``--lift`` is the sole
thickness the body stands on (the blueprint's barefoot numbers are compared
after removing it). Nothing here is a pass/fail gate; it is the evidence
list the blueprint's QA section asks for.
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from promodeler.human.mhr import blueprint_targets  # noqa: E402


def latest(pattern: str) -> str | None:
    matches = glob.glob(pattern)
    return max(matches, key=os.path.getmtime) if matches else None


def row(label: str, target, got, unit: str = "m", tolerance: float | None = None) -> str:
    if target is None or got is None:
        return f"  {label:28s} {'-' if target is None else f'{target:.3f}':>8}  {'-' if got is None else f'{got:.3f}':>8}"
    diff = got - target
    scale = 1000.0 if unit == "m" else 1.0
    flag = ""
    if tolerance is not None:
        flag = "  ok" if abs(diff) <= tolerance else f"  OVER (tol {tolerance * scale:.0f} {'mm' if unit == 'm' else unit})"
    return f"  {label:28s} {target:8.3f}  {got:8.3f}  {diff * scale:+8.1f} {'mm' if unit == 'm' else unit}{flag}"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("blueprint")
    parser.add_argument("build_dir", nargs="?")
    parser.add_argument("--lift", type=float, default=0.025, help="sole thickness the body stands on")
    parser.add_argument("--asset", default="haruka", help="asset directory name under build/ and human body name")
    args = parser.parse_args()

    blueprint = json.load(open(args.blueprint, encoding="utf-8"))
    dims = blueprint["dimensions"]
    build_dir = args.build_dir or latest(f"build/{args.asset}/*/report.json")
    if build_dir and build_dir.endswith("report.json"):
        build_dir = os.path.dirname(build_dir)
    report = json.load(open(os.path.join(build_dir, "report.json"), encoding="utf-8")) if build_dir else None
    rig_path = latest(f"build/human/{args.asset}-*/rig.json")
    rig = json.load(open(rig_path, encoding="utf-8")) if rig_path else None
    body = np.load(rig_path.replace("rig.json", "body.npz"))["vertices"] if rig_path else None
    lift = args.lift

    print(f"blueprint: {blueprint.get('name')} ({args.blueprint})")
    print(f"build:     {build_dir}")
    print(f"body fit:  {rig_path}")

    print("\n[fit measurements]            target       got      diff")
    if rig:
        measured = rig["measurements"]
        for key, target in blueprint_targets(blueprint).items():
            tol = 0.002 if key == "height" else (0.005 if key.endswith(("_width", "_depth")) else None)
            print(row(key, target, measured.get(key), tolerance=tol))
        joints_bp = {j["id"]: j for j in blueprint.get("rig", {}).get("joints", [])}
        if "upperarm.L" in joints_bp and "upperarm.R" in joints_bp and "joint_shoulder_width" in measured:
            span = abs(joints_bp["upperarm.L"]["head_m"][0] - joints_bp["upperarm.R"]["head_m"][0])
            print(row("shoulder joint distance", span, measured["joint_shoulder_width"]))
        if "bust_bump_m" in measured:
            print(f"  {'bust geometric bump':28s} {'-':>8}  {measured['bust_bump_m']:8.3f}   (added to MHR identity)")

    if body is not None:
        print("\n[barefoot body]")
        print(row("height (QA +-2 mm)", dims["barefoot_height_m"], float(body[:, 1].max() - body[:, 1].min()), tolerance=0.002))
        if report:
            body_bounds = report["parts"]["body"]["bounds"]
            print(row("shod height (body top)", dims.get("standing_shod_height_m"), body_bounds["max"][1]))
            print(row("sole thickness", dims.get("shoe_sole_m"), lift))

    if report:
        print("\n[parts vs blueprint boxes]      target       got      diff   (blueprint sizes exclude the A-pose arms)")
        parts = report["parts"]
        for spec in blueprint.get("parts", []):
            ids = {"hair": ("hair", "hair_strands")}.get(spec["id"], (spec["id"],))
            present = [parts[i]["bounds"] for i in ids if i in parts]
            if not present:
                print(f"  {spec['id']:28s} missing in build")
                continue
            lo = [min(b["min"][k] for b in present) for k in range(3)]
            hi = [max(b["max"][k] for b in present) for k in range(3)]
            size = [hi[k] - lo[k] for k in range(3)]
            center = [(hi[k] + lo[k]) / 2 for k in range(3)]
            center[1] -= lift
            for axis, k in (("x", 0), ("y", 1), ("z", 2)):
                print(row(f"{spec['id']} size {axis}", spec["size_m"][k], size[k]))
                print(row(f"{spec['id']} center {axis}", spec["center_m"][k], center[k]))
        if "dress" in parts:
            print(row("dress hem height", dims.get("dress_hem_height_m"), parts["dress"]["bounds"]["min"][1] - lift))
        hair_ids = [i for i in ("hair", "hair_strands") if i in parts]
        if hair_ids and body is not None:
            tip = min(parts[i]["bounds"]["min"][1] for i in hair_ids) - lift
            crown = float(body[:, 1].max())
            print(row("hair length (crown to tip)", dims.get("hair_length_m"), crown - tip))

        print("\n[budgets]                        max       got")
        target = blueprint.get("target", {})
        total = report["totals"]["triangles"] if "totals" in report and "triangles" in report["totals"] else sum(p["triangles"] for p in parts.values())
        print(row("triangles lod0", target.get("triangles_lod0_max"), total, unit="tris"))
        groups = {"body": ("body",), "hair": ("hair", "hair_strands"), "dress": ("dress",),
                  "shoes": ("sole_l", "shoe_l", "laces_l", "sole_r", "shoe_r", "laces_r"), "eyes_teeth": ("eye_l", "eye_r")}
        for name, budget in target.get("triangles_by_part", {}).items():
            got = sum(parts[i]["triangles"] for i in groups.get(name, (name,)) if i in parts)
            print(row(f"triangles {name}", budget, got, unit="tris"))
        density = max((p.get("uv", {}).get("texel_density_px_per_m", 0) for p in parts.values()), default=0)
        print(row("texel density (best part)", target.get("texel_density_px_per_m"), density, unit="px/m"))
        print(f"\n  warnings: {len(report.get('warnings', []))}")
        for warning in report.get("warnings", []):
            print(f"    {warning['code']}: {warning['message']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
