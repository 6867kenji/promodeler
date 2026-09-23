"""Building blocks for garments cut on a race profile (``character/profiles/<race>.json``, docs/03 18.8 / 18.13).

A profile gives the neutral body of a race as torso outlines by height and limb cross-sections along each limb axis.
The helpers here turn those into ``Loft`` sections with the ease added and a shared point order, so a generator
under ``assets/wardrobe`` only decides which slices to use and how much ease to give.

Frame: the Unity body frame (metres, Y up, the character faces +Z, left arm toward -X). ``LoftSection`` points lie on
the local XZ plane facing +Y, ``(u, v) -> (u, 0, -v)``; the transforms below place that plane on the torso (Y axis)
or on a limb axis with the section's own basis.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

from .core import LoftSection, ModelingError, Transform

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PROFILE_SCHEMA = "promodeler-race-profile/1.0"


def load_profile(path: str | Path) -> dict:
    full = Path(path) if Path(path).is_absolute() else PROJECT_ROOT / path
    if not full.is_file():
        raise ModelingError("garment.profile", f"race profile not found: {full} (run `promodeler character profile <race>`).")
    profile = json.loads(full.read_text(encoding="utf-8"))
    if profile.get("schema") != PROFILE_SCHEMA:
        raise ModelingError("garment.profile", f"{full} is not a {PROFILE_SCHEMA} document.")
    return profile


def resample_outline(points, ease: float, count: int) -> list[tuple[float, float]]:
    """A convex outline (a, b) pushed outward by ``ease`` and resampled at ``count`` uniform polar angles from its
    centroid, starting at +b, so every section of a loft shares its point order."""
    if not points:
        raise ModelingError("garment.profile", "empty outline in the race profile.")
    cx = sum(a for a, _ in points) / len(points)
    cy = sum(b for _, b in points) / len(points)
    polar = sorted(((math.atan2(a - cx, b - cy), math.hypot(a - cx, b - cy) + ease) for a, b in points))
    angles = [t for t, _ in polar] + [polar[0][0] + 2 * math.pi]
    radii = [r for _, r in polar] + [polar[0][1]]
    out = []
    for i in range(count):
        theta = -math.pi + 2 * math.pi * i / count
        t = theta if theta >= angles[0] else theta + 2 * math.pi
        j = 0
        while j + 1 < len(angles) and angles[j + 1] < t:
            j += 1
        a0, a1 = angles[j], angles[min(j + 1, len(angles) - 1)]
        r0, r1 = radii[j], radii[min(j + 1, len(radii) - 1)]
        f = 0.0 if a1 <= a0 else (t - a0) / (a1 - a0)
        r = r0 + (r1 - r0) * max(0.0, min(1.0, f))
        out.append((cx + r * math.sin(theta), cy + r * math.cos(theta)))
    return out


def euler_from_basis(x_axis, y_axis, z_axis) -> tuple[float, float, float]:
    """XYZ Euler angles (Blender order, Rz * Ry * Rx) of the rotation whose columns are the three axis images."""
    m = [[x_axis[0], y_axis[0], z_axis[0]], [x_axis[1], y_axis[1], z_axis[1]], [x_axis[2], y_axis[2], z_axis[2]]]
    ry = math.asin(max(-1.0, min(1.0, -m[2][0])))
    if abs(math.cos(ry)) > 1e-6:
        rx = math.atan2(m[2][1], m[2][2])
        rz = math.atan2(m[1][0], m[0][0])
    else:  # gimbal lock: fold everything into rz
        rx = 0.0
        rz = math.atan2(-m[0][1], m[1][1])
    return rx, ry, rz


def torso_sections(profile: dict, y_from: float, y_to: float, ease: float, count: int, margin: float = 0.0) -> list[LoftSection]:
    """Horizontal torso sections between two heights (inclusive of the slices within ``margin`` outside the range)."""
    sections = []
    for slice_ in sorted(profile["torso_slices"], key=lambda s: s["y"]):
        y = float(slice_["y"])
        if y < y_from - margin or y > y_to + margin:
            continue
        ring = resample_outline(slice_["points"], ease, count)
        sections.append(LoftSection(points=tuple((x, -z) for x, z in ring), transform=Transform(translation=(0.0, y, 0.0))))
    return sections


def limb_basis(limb: dict) -> tuple[tuple[float, float, float], tuple[float, float, float], tuple[float, float, float]]:
    """(e1, dir, e2) of a limb as the profile defines them: arms carry ``angle_z`` (e2 = +Z), legs carry e1/e2."""
    direction = tuple(float(c) for c in limb["dir"])
    if "angle_z" in limb:
        angle = float(limb["angle_z"])
        e1 = (math.cos(angle), math.sin(angle), 0.0)
        e2 = (0.0, 0.0, 1.0)
    else:
        e1 = tuple(float(c) for c in limb["e1"])
        e2 = tuple(float(c) for c in limb["e2"])
    return e1, direction, e2


def limb_sections(limb: dict, t_from: float, t_to: float, ease: float, count: int, root_extension: float = 0.0) -> list[LoftSection]:
    """Cross-sections of an arm or leg between two axial parameters (metres from the joint), each on the plane
    perpendicular to the limb axis. ``root_extension`` repeats the first section that far back along the axis
    (buried inside the torso) so the tube joins the body part without a gap."""
    e1, direction, e2 = limb_basis(limb)
    # Local X -> e1, local Y -> the axis, local Z -> the image of local Z. Section points are (u, v) -> (u, 0, -v),
    # so v = -b puts b along e2 when local Z maps onto e2 ... which needs (e1, dir, e2) right-handed: arms are
    # (e1 x dir = +Z = e2); legs from the exporter are left-handed (e2 = dir x e1), so flip v there instead.
    handed = _cross(e1, direction)
    right_handed = _dot(handed, e2) > 0.0
    z_axis = e2 if right_handed else tuple(-c for c in e2)
    rotation = euler_from_basis(e1, direction, z_axis)
    sign = -1.0 if right_handed else 1.0   # v = -b (right-handed) or v = +b (left-handed) both land b on e2
    sections = []
    slices = [s for s in limb["slices"] if t_from - 1e-6 <= float(s["t"]) <= t_to + 1e-6]
    if len(slices) < 2:
        raise ModelingError("garment.profile", f"fewer than two limb sections between t={t_from} and t={t_to}.")
    for i, slice_ in enumerate(slices):
        ring = resample_outline(slice_["points"], ease, count)
        points = tuple((a, sign * b) for a, b in ring)
        centre = tuple(float(c) for c in slice_["center"])
        if i == 0 and root_extension > 0.0:
            root = tuple(centre[k] - root_extension * direction[k] for k in range(3))
            sections.append(LoftSection(points=points, transform=Transform(translation=root, rotation=rotation)))
        sections.append(LoftSection(points=points, transform=Transform(translation=centre, rotation=rotation)))
    return sections


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def garment_extras(profile: dict, profile_path: str, wardrobe_slot: str, **more) -> dict:
    return {"promodeler_garment": {"race": profile.get("race"), "uma_race": profile.get("uma_race"), "profile": str(profile_path),
                                   "wardrobe_slot": wardrobe_slot, "frame": "unity body frame (metres, Y up, faces +Z)", **more}}
