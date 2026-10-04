"""Report conservative camera-frustum triangle counts for a built city.

Usage: python audit_visibility.py BUILD_DIR

Every mesh whose bounding sphere meets a camera frustum is counted in full.
This deliberately overestimates visible triangles; it does not claim to model
occlusion by buildings, roofs, or terrain.
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path


def dot(a, b):
    return sum(x * y for x, y in zip(a, b))


def subtract(a, b):
    return tuple(x - y for x, y in zip(a, b))


def cross(a, b):
    return (a[1] * b[2] - a[2] * b[1],
            a[2] * b[0] - a[0] * b[2],
            a[0] * b[1] - a[1] * b[0])


def unit(vector):
    length = math.sqrt(dot(vector, vector))
    return tuple(value / length for value in vector)


def frustum_upper_bound(camera: dict, parts: dict, aspect: float) -> tuple[int, int]:
    position = camera["position"]
    forward = unit(subtract(camera["target"], position))
    right = unit(cross(forward, (0, 1, 0)))
    up = cross(right, forward)
    if camera["orthographic"]:
        # Blender's scale and sensor fit can vary; this larger box is safe.
        half_height = camera["ortho_scale"] / 2
        half_width = half_height * max(1, aspect)
    else:
        # Apply the wider FOV on both axes for a conservative upper bound.
        tangent = math.tan(camera["fov"] / 2)
    triangles = objects = 0
    hidden = set(camera.get("hide_parts") or ())
    for part_id, part in parts.items():
        if part_id in hidden or not part.get("bounds"):
            continue
        minimum, maximum = part["bounds"]["min"], part["bounds"]["max"]
        center = tuple((lo + hi) / 2 for lo, hi in zip(minimum, maximum))
        radius = math.sqrt(sum((hi - lo) ** 2 for lo, hi in zip(minimum, maximum))) / 2
        relative = subtract(center, position)
        depth = dot(relative, forward)
        horizontal = dot(relative, right)
        vertical = dot(relative, up)
        if depth + radius < camera["clip_start"]:
            continue
        if camera["orthographic"]:
            if abs(horizontal) - radius > half_width or abs(vertical) - radius > half_height:
                continue
        else:
            extent = max(depth + radius, camera["clip_start"]) * tangent
            if abs(horizontal) - radius > extent or abs(vertical) - radius > extent:
                continue
        triangles += part["triangles"]
        objects += 1
    return triangles, objects


def audit(build_dir: Path) -> dict:
    recipe = json.loads((build_dir / "recipe.json").read_text(encoding="utf-8"))
    report = json.loads((build_dir / "report.json").read_text(encoding="utf-8"))
    blueprint = json.loads(Path(__file__).with_name("blueprint.json").read_text(encoding="utf-8"))
    target = blueprint["target"]
    aspect = recipe["render"]["aspect_ratio"]
    cameras = {}
    for camera in recipe["render"]["cameras"]:
        triangles, objects = frustum_upper_bound(camera, report["parts"], aspect)
        cameras[camera["id"]] = {"triangleUpperBound": triangles, "partCount": objects,
                                 "underVisibleTarget": triangles <= target["triangles_visible_target"]}
    local_views = {name: result for name, result in cameras.items()
                   if name not in {"district_oblique", "district_plan"}}
    overview = {name: result for name, result in cameras.items() if name not in local_views}
    return {
        "method": "conservative full-part bounding-sphere camera-frustum count; no occlusion reduction",
        "sceneTriangles": report["totals"]["triangles"],
        "lod0Budget": target["triangles_lod0_max"],
        "lod0UnderBudget": report["totals"]["triangles"] <= target["triangles_lod0_max"],
        "visibleTriangleTarget": target["triangles_visible_target"],
        "localViewsUnderTarget": all(result["underVisibleTarget"] for result in local_views.values()),
        "overviewRequiresOcclusionOrLodReview": any(not result["underVisibleTarget"]
                                                     for result in overview.values()),
        "cameras": cameras,
    }


if __name__ == "__main__":
    root = Path(sys.argv[1]).resolve()
    result = audit(root)
    (root / "visibility-audit.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps({key: value for key, value in result.items() if key != "cameras"}, indent=2))
