"""Compare a finished non-character build with its numerical blueprint.

Concept images are deliberately excluded: they describe appearance but are
not measurement evidence. Asset modules may map one blueprint part to several
mesh parts and add explicit detail IDs that must survive future revisions.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence


def _bounds_for(parts: Mapping[str, dict], ids: Sequence[str]) -> dict:
    return {
        "min": [min(parts[part_id]["bounds"]["min"][axis] for part_id in ids) for axis in range(3)],
        "max": [max(parts[part_id]["bounds"]["max"][axis] for part_id in ids) for axis in range(3)],
    }


def _difference(actual: dict, center: Sequence[float], size: Sequence[float]) -> float:
    target_min = [c - s / 2 for c, s in zip(center, size)]
    target_max = [c + s / 2 for c, s in zip(center, size)]
    return max(abs(a - b) for side, target in (("min", target_min), ("max", target_max))
               for a, b in zip(actual[side], target))


def check_blueprint(
    blueprint: dict,
    recipe: dict,
    report: dict,
    *,
    part_map: Mapping[str, Sequence[str]] | None = None,
    motion_map: Mapping[str, str] | None = None,
    required_parts: Sequence[str] = (),
    texel_parts: Sequence[str] | None = None,
    envelope_mode: str = "exact",
    prototype_parts: Sequence[str] = (),
) -> dict:
    """Return measurable discrepancies without changing the kernel success state."""
    part_map = part_map or {}
    motion_map = motion_map or {}
    issues: list[dict[str, str]] = []

    def issue(severity: str, code: str, message: str) -> None:
        issues.append({"severity": severity, "code": code, "message": message})

    parts = report.get("parts", {})
    recipe_parts = {part["id"]: part for part in recipe["asset"]["parts"]}
    dims = blueprint.get("dimensions", {})
    envelope = dims.get("envelope_xyz_m")
    if envelope_mode == "scheduled":
        specified = [part for part in blueprint.get("parts", [])
                     if "center_m" in part and "size_m" in part]
        if specified:
            envelope = [
                max(part["center_m"][axis] + part["size_m"][axis] / 2 for part in specified)
                - min(part["center_m"][axis] - part["size_m"][axis] / 2 for part in specified)
                for axis in range(3)
            ]
    if envelope and report.get("bounds"):
        actual = [hi - lo for lo, hi in zip(report["bounds"]["min"], report["bounds"]["max"])]
        for axis, (got, expected) in enumerate(zip(actual, envelope)):
            tolerance = max(0.015, expected * 0.005)
            maximum = envelope_mode == "maximum" or (envelope_mode == "height_maximum" and axis == 1)
            if (got > expected + tolerance if maximum else abs(got - expected) > tolerance):
                issue("error", "blueprint.envelope", f"Axis {axis}: {got:.3f} m, expected {expected:.3f} m.")

    target = blueprint.get("target", {})
    triangle_limit = target.get("triangles_lod0_max")
    if triangle_limit is not None and report.get("totals", {}).get("triangles", 0) > triangle_limit:
        issue("error", "blueprint.triangles", f"Triangle count exceeds {triangle_limit}.")
    texture_limit = target.get("texture_resolution_max")
    if texture_limit is not None:
        default_resolution = ((recipe.get("input") or {}).get("quality") or {}).get("texture_resolution", 1024)
        for part in recipe["asset"]["parts"]:
            if (part.get("texture_resolution") or default_resolution) > texture_limit:
                issue("error", "blueprint.textureBudget", f"{part['id']}: texture exceeds {texture_limit} px.")

    material_ids = {material["id"] for material in recipe["asset"]["materials"]}
    for material in blueprint.get("materials", []):
        if material["id"] not in material_ids:
            issue("error", "blueprint.material", f"Missing material {material['id']!r}.")

    for expected in blueprint.get("parts", []):
        expected_id = expected["id"]
        normalized = expected_id.replace("-", "_")
        members = tuple(part_map.get(expected_id) or (
            part_id for part_id in parts if part_id == normalized or part_id.startswith(normalized + "_")
        ))
        missing = [part_id for part_id in members if part_id not in parts]
        if not members or missing:
            issue("error", "blueprint.part", f"{expected_id}: missing mesh part(s) {missing or [normalized]}.")
            continue
        if "center_m" in expected and "size_m" in expected:
            bounds = _bounds_for(parts, members)
            if expected_id in prototype_parts:
                deviation = max(abs((hi - lo) - size) for lo, hi, size in
                                zip(bounds["min"], bounds["max"], expected["size_m"]))
            else:
                deviation = _difference(bounds, expected["center_m"], expected["size_m"])
            if deviation > 0.02:
                issue("error", "blueprint.partBounds", f"{expected_id}: envelope differs by up to {deviation:.3f} m.")
        expected_material = expected.get("material")
        if expected_material and not any(recipe_parts[part_id]["material"] == expected_material for part_id in members):
            issue("error", "blueprint.partMaterial", f"{expected_id}: expected material {expected_material!r} is absent.")

    for part_id in required_parts:
        if part_id not in parts:
            issue("error", "blueprint.detail", f"Missing required detail {part_id!r}.")

    joints = {joint["id"]: joint for joint in (recipe["asset"].get("rig") or {}).get("joints", [])}
    open_poses = [pose for pose in recipe["asset"].get("poses", []) if pose["id"] == "open"]
    open_joints = open_poses[0]["joints"] if open_poses else {}
    for motion in blueprint.get("motions", []):
        motion_id = motion["id"]
        joint_id = motion_map.get(motion_id, motion_id.replace("-", "_"))
        joint = joints.get(joint_id)
        if joint is None:
            issue("error", "blueprint.motion", f"{motion_id}: missing joint {joint_id!r}.")
        elif "pivot_m" in motion and max(abs(a - b) for a, b in zip(joint["head"], motion["pivot_m"])) > 0.015:
            issue("error", "blueprint.motionPivot", f"{motion_id}: pivot differs from the blueprint.")
        if joint is not None and "range" in motion and joint_id not in open_joints:
            issue("error", "blueprint.motionPose", f"{motion_id}: open pose is missing joint {joint_id!r}.")
        if joint is not None and joint_id in open_joints and "range" in motion and "axis" in motion:
            axis = max(range(3), key=lambda index: abs(motion["axis"][index]))
            channel = "rotation" if motion.get("unit") == "degree" else "translation"
            expected = max(abs(float(value)) for value in motion["range"])
            actual = abs(open_joints[joint_id][channel][axis])
            if channel == "rotation":
                expected = math.radians(expected)
            if abs(actual - expected) > (math.radians(2) if channel == "rotation" else 0.02):
                issue("error", "blueprint.motionRange", f"{motion_id}: open pose does not reach the specified range.")

    density_target = target.get("texel_density_px_per_m")
    if density_target:
        density_ids = set(parts if texel_parts is None else texel_parts)
        for part_id in density_ids - parts.keys():
            issue("error", "blueprint.texelPart", f"Texture density target names missing part {part_id!r}.")
        below = [(part_id, stats["uv"]["texel_density_px_per_m"])
                 for part_id, stats in parts.items()
                 if part_id in density_ids and "uv" in stats
                 and stats["uv"]["texel_density_px_per_m"] < density_target]
        if below:
            worst_id, worst_density = min(below, key=lambda item: item[1])
            issue("warning", "blueprint.texelDensity",
                  f"{len(below)} baked parts are below {density_target} px/m; lowest is {worst_id} at {worst_density:.1f} px/m.")

    return {
        "id": blueprint.get("id"),
        "status": "pass" if not issues else "needs_work",
        "issues": issues,
    }
