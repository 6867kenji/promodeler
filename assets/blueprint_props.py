"""Detailed small-object generators built from 07–16 numerical part schedules."""

from __future__ import annotations

import math
from dataclasses import replace

from promodeler.core import (
    Array, Asset, Bevel, Boolean, Box, Clip, Color, Cutter, Cylinder,
    Joint, JointTransform, Keyframe, Material, Part, Pose, Rig, Sphere,
    Transform,
)

from assets.blueprint_materials import materials_for


FOCAL_TEXTURE_PARTS = {
    "07-bed": ("detail_headboard_grain", "mattress", "pillow", "duvet-folded"),
    "08-sofa": ("seat-0", "seat-1", "back-0", "back-1"),
    "10-table-chair": ("table-top", "chair-seat", "chair-back"),
    "11-pc-desk": ("top",),
    "15-gaming-pc-white": ("tower-shell", "monitor-panel", "active-screen", "keyboard"),
    "16-gaming-pc-pink": ("tower-shell", "monitor-panel", "active-screen", "keyboard"),
}


def joint_id(motion_id: str) -> str:
    return "j_" + motion_id.replace("-", "_")


PARENT_MOTIONS = {
    "09-ceiling-light": {"rim": "cover-release", "diffuser": "cover-release"},
    "11-pc-desk": {"grommet": "grommet-cap"},
    "12-pc-set": {"monitor-panel": "monitor-tilt", "monitor-stand": "monitor-height"},
    "13-refrigerator": {"upper-door": "upper-door", "lower-door": "lower-door",
                        "crisper": "crisper", "freezer-bin-0": "freezer-bin",
                        "freezer-bin-1": "freezer-bin"},
    "14-microwave": {"door": "door", "handle": "door", "dial-0": "dial-upper",
                     "dial-1": "dial-lower", "turntable": "turntable"},
    "15-gaming-pc-white": {"monitor-panel": "monitor-tilt", "active-screen": "monitor-tilt",
                           "monitor-stand": "monitor-height", "left-glass": "glass-release",
                           "fan-front-0": "fan-front", "fan-front-1": "fan-front",
                           "fan-front-2": "fan-front", "fan-cpu": "fan-cpu"},
    "16-gaming-pc-pink": {"monitor-panel": "monitor-tilt", "active-screen": "monitor-tilt",
                          "monitor-stand": "monitor-height", "left-glass": "glass-release",
                          "fan-front-0": "fan-front", "fan-front-1": "fan-front",
                          "fan-front-2": "fan-front", "fan-cpu": "fan-cpu"},
}


JOINT_PARENTS = {
    "09-ceiling-light": {"cover-release": "cover-drop"},
    "12-pc-set": {"monitor-tilt": "monitor-height"},
    "15-gaming-pc-white": {"monitor-tilt": "monitor-swivel", "monitor-swivel": "monitor-height",
                           "glass-release": "glass-remove"},
    "16-gaming-pc-pink": {"monitor-tilt": "monitor-swivel", "monitor-swivel": "monitor-height",
                          "glass-release": "glass-remove"},
}


def rig_for(design: dict, folder: str):
    motions = design.get("motions", [])
    if not motions:
        return None, (), ()
    parents = JOINT_PARENTS.get(folder, {})
    joints = []
    open_transforms = {}
    for motion in motions:
        mid = motion["id"]
        head = tuple(motion["pivot_m"])
        axis = tuple(motion["axis"])
        tail = tuple(a + b for a, b in zip(head, axis))
        joints.append(Joint(joint_id(mid), head=head, tail=tail,
                            parent=joint_id(parents[mid]) if mid in parents else None))
        span = motion["range"]
        end = max(span, key=lambda number: abs(number))
        values = tuple(a * (math.radians(end) if motion["unit"] == "degree" else end) for a in axis)
        open_transforms[joint_id(mid)] = (JointTransform(rotation=values, space="world")
                                          if motion["unit"] == "degree"
                                          else JointTransform(translation=values, space="world"))
    pose = Pose("open", open_transforms)
    clip = Clip("open-close", duration=4, loop=False,
                keyframes=(Keyframe(0, None), Keyframe(2, "open"), Keyframe(4, None)))
    return Rig(design["id"], joints=tuple(joints)), (pose,), (clip,)


def _shape_and_modifiers(folder: str, part: dict):
    pid = part["id"]
    sx, sy, sz = part["size_m"]
    rotation = (0.0, 0.0, 0.0)
    modifiers = []
    if folder == "09-ceiling-light" and pid in {"mount", "chassis", "rim", "diffuser"}:
        shape = Cylinder(radius=sx / 2, height=sy, segments=48)
        if pid == "rim":
            modifiers.append(Boolean("difference", cutter=Cutter(
                shape=Cylinder(radius=sx * 0.42, height=sy + 0.01, segments=48))))
    elif pid.startswith("fan-") or pid.startswith("dial-") or pid in {"turntable", "grommet"}:
        if pid == "turntable":
            radius = min(sx, sz) / 2
            height = sy
        elif pid == "grommet":
            radius = sx / 2
            height = sy
        else:
            if sx < min(sy, sz):
                radius, height = min(sy, sz) / 2, sx
                rotation = (0.0, 0.0, math.pi / 2)
            else:
                radius, height = min(sx, sy) / 2, sz
                rotation = (math.pi / 2, 0.0, 0.0)
        shape = Cylinder(radius=radius, height=height, segments=32)
        if pid.startswith("fan-"):
            modifiers.append(Boolean("difference", cutter=Cutter(
                shape=Cylinder(radius=radius * 0.62, height=height + 0.005, segments=32))))
        elif pid == "grommet":
            modifiers.append(Boolean("difference", cutter=Cutter(
                shape=Cylinder(radius=radius * 0.55, height=height + 0.005, segments=32))))
    elif pid in {"mouse", "pillow"}:
        shape = Sphere(radius=0.5, segments=24, rings=12)
    else:
        shape = Box(size=(sx, sy, sz))
        if pid in {"cabinet-shell", "shell", "cavity"} and folder in {"13-refrigerator", "14-microwave"}:
            inset = 0.035 if folder == "13-refrigerator" else 0.025
            cutter = Box(size=(sx - 2 * inset, sy - 2 * inset, sz - inset))
            modifiers.append(Boolean("difference", cutter=Cutter(
                shape=cutter, transform=Transform(translation=(0, 0, inset)))))
        elif pid == "tower-shell" and folder.startswith(("15-", "16-")):
            cutter = Box(size=(sx * 0.82, sy * 0.87, sz * 0.88))
            modifiers.append(Boolean("difference", cutter=Cutter(
                shape=cutter, transform=Transform(translation=(-sx * 0.16, 0, 0)))))
            # Three separate apertures expose the specified front RGB fans.
            # The shell's front skin otherwise occludes every fan in the GLB.
            for fan_y in (0.13, 0.25, 0.37):
                modifiers.append(Boolean("difference", cutter=Cutter(
                    shape=Cylinder(radius=0.061, height=0.08, segments=32),
                    transform=Transform(translation=(0, fan_y - 0.23, sz / 2 - 0.012),
                                        rotation=(math.pi / 2, 0, 0)))))
        elif pid == "door" and folder == "14-microwave":
            cutter = Box(size=(sx - 0.055, sy - 0.045, sz + 0.008))
            modifiers.append(Boolean("difference", cutter=Cutter(shape=cutter)))
        softness = 0.035 if pid in {"mattress", "pillow", "duvet-folded"} or pid.startswith(("seat-", "back-", "arm-")) else 0.008
        width = min(softness, min(sx, sy, sz) * 0.18)
        if width > 0.0003:
            modifiers.append(Bevel(width=width, segments=3))
    return shape, tuple(modifiers), rotation


def _part(design: dict, folder: str, part: dict, textured: set[str]) -> Part:
    pid = part["id"]
    size = tuple(part["size_m"])
    shape, modifiers, rotation = _shape_and_modifiers(folder, part)
    # The unit-sphere shape is scaled to the exact scheduled pillow/mouse envelope.
    scale = size if isinstance(shape, Sphere) else (1.0, 1.0, 1.0)
    motion = PARENT_MOTIONS.get(folder, {}).get(pid)
    return Part(id=pid, shape=shape, material=part["material"],
                transform=Transform(translation=tuple(part["center_m"]), rotation=rotation, scale=scale),
                modifiers=modifiers, parent_joint=joint_id(motion) if motion else None,
                texture_resolution=((4096 if folder.startswith(("15-", "16-")) else 2048)
                                    if pid in FOCAL_TEXTURE_PARTS.get(folder, ()) else 256)
                if part["material"] in textured else None,
                smooth_angle=math.radians(35))


def _detail_box(parts: list[Part], pid: str, size, center, material, *, bevel=0.0,
                parent: str | None = None, texture_resolution=None):
    modifiers = (Bevel(width=bevel, segments=3),) if bevel else ()
    parts.append(Part(id=pid, shape=Box(size=tuple(size)), material=material,
                      transform=Transform(translation=tuple(center)), modifiers=modifiers,
                      parent_joint=joint_id(parent) if parent else None,
                      texture_resolution=texture_resolution))


def detail_parts(design: dict, folder: str, parts: list[Part]) -> list[Material]:
    extra_materials = []
    if folder in {"07-bed", "08-sofa"}:
        # Narrow piping gives upholstery a readable edge without adding a dark seam texture.
        if folder == "07-bed":
            oak = next(spec for spec in design["materials"] if spec["id"] == "oak")
            extra_materials.append(replace(materials_for({"materials": [oak]})[0], id="oak_veneer"))
            _detail_box(parts, "detail_headboard_grain", (1.0, 0.64, 0.001),
                        (0, 0.465, -0.9885), "oak_veneer", texture_resolution=2048)
            for side, x in (("l", -0.478), ("r", 0.478)):
                _detail_box(parts, f"detail_mattress_piping_{side}", (0.005, 0.005, 1.92),
                            (x, 0.425, 0), "foam", bevel=0.001)
        else:
            _detail_box(parts, "detail_seat_seam", (0.005, 0.004, 0.46),
                        (0, 0.402, 0.085), "foam")
    if folder in {"12-pc-set", "15-gaming-pc-white", "16-gaming-pc-pink"}:
        keyboard = next(p for p in design["parts"] if p["id"] == "keyboard")
        x, y, z = keyboard["center_m"]
        sx, sy, sz = keyboard["size_m"]
        key_w = (sx - 0.03) / 14 * 0.7
        key_z = (sz - 0.025) / 4 * 0.7
        _detail_box(parts, "detail_keyboard_keys", (key_w, 0.006, key_z),
                    (x - sx / 2 + 0.03, y + sy / 2 + 0.003, z - sz / 2 + 0.024),
                    "keycap" if folder.startswith(("15-", "16-")) else "black-plastic")
        key_part = parts[-1]
        parts[-1] = Part(id=key_part.id, shape=key_part.shape, material=key_part.material,
                         transform=key_part.transform,
                         modifiers=(Array(count=14, offset=((sx - 0.06) / 13, 0, 0)),
                                    Array(count=4, offset=(0, 0, (sz - 0.048) / 3))))
        if folder == "12-pc-set":
            extra_materials.append(Material("screen-glow", base_color=Color(0.035, 0.09, 0.16),
                                            roughness=0.2, emission_color=Color(0.08, 0.28, 0.42),
                                            emission_strength=0.65))
            _detail_box(parts, "detail_monitor_screen", (0.51, 0.29, 0.002),
                        (-0.17, 0.238, -0.128), "screen-glow", parent="monitor-tilt")
    if folder == "13-refrigerator":
        for name, y in (("upper", 0.88), ("lower", 0.24)):
            _detail_box(parts, f"detail_handle_{name}", (0.014, 0.19, 0.018),
                        (-0.19, y, 0.286), "metal", bevel=0.004, parent=f"{name}-door")
            _detail_box(parts, f"detail_gasket_{name}", (0.45, 0.012, 0.006),
                        (0, 0.465 if name == "lower" else 1.27, 0.242), "gasket")
    if folder == "14-microwave":
        _detail_box(parts, "detail_door_glass", (0.275, 0.165, 0.004),
                    (-0.0475, 0.14, 0.154), "glass", parent="door")
        _detail_box(parts, "detail_clock", (0.055, 0.022, 0.004),
                    (0.1725, 0.225, 0.157), "black-plastic")
        for index in range(5):
            _detail_box(parts, f"detail_vent_{index}", (0.02, 0.002, 0.006),
                        (0.115 + index * 0.019, 0.252, -0.08), "black-plastic")
    if folder.startswith(("15-", "16-")):
        for index, y in enumerate((0.13, 0.25, 0.37)):
            _detail_box(parts, f"detail_fan_hub_{index}", (0.035, 0.035, 0.008),
                        (0.32, y, 0.143), "metal", parent="fan-front")
        _detail_box(parts, "detail_power_switch", (0.016, 0.006, 0.016),
                    (0.32, 0.448, 0.1), "keycap")
    return extra_materials


def build_prop(design: dict, folder: str) -> Asset:
    materials = list(materials_for(design, textured_ids={"fabric"} if folder == "07-bed" else
                                   {"fabric"} if folder == "08-sofa" else None))
    textured = {material.id for material in materials if material.needs_bake}
    parts = [_part(design, folder, part, textured) for part in design["parts"]]
    materials.extend(detail_parts(design, folder, parts))
    rig, poses, clips = rig_for(design, folder)
    return Asset(name=design["id"], materials=tuple(materials), parts=tuple(parts),
                 rig=rig, poses=poses, clips=clips)
