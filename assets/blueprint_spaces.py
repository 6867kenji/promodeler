"""Station interiors and tenant spaces from the numerical design sheets."""

from __future__ import annotations

from dataclasses import replace

from promodeler.core import Asset, Bevel, Box, Color, Material, Part, Transform

from assets.blueprint_materials import materials_for, texture_resolution_for
from assets.blueprint_props import joint_id, rig_for


def _box(parts: list[Part], name: str, bounds, material: str, *, bevel=0.0,
         joint: str | None = None, texture_resolution=None) -> None:
    x0, x1, y0, y1, z0, z1 = bounds
    size = (x1 - x0, y1 - y0, z1 - z0)
    parts.append(Part(
        id=name, shape=Box(size=size), material=material,
        transform=Transform(translation=((x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2)),
        modifiers=(Bevel(width=bevel, segments=3),) if bevel else (),
        parent_joint=joint_id(joint) if joint else None,
        texture_resolution=texture_resolution,
    ))


def _scheduled_parts(design: dict, folder: str) -> list[Part]:
    parts = []
    for entry in design["parts"]:
        x, y, z = entry["center_m"]
        sx, sy, sz = entry["size_m"]
        pid = entry["id"]
        if folder == "20-cafe" and pid.startswith("table-"):
            _box(parts, pid + "_top", (x - sx / 2, x + sx / 2, sy - 0.025, sy,
                                       z - sz / 2, z + sz / 2), "oak", bevel=0.004)
            _box(parts, pid + "_stem", (x - 0.028, x + 0.028, 0.025, sy - 0.025,
                                        z - 0.028, z + 0.028), "bronze")
            _box(parts, pid + "_base", (x - 0.16, x + 0.16, 0, 0.025,
                                        z - 0.16, z + 0.16), "bronze")
            continue
        if folder == "20-cafe" and pid.startswith("chair-"):
            _box(parts, pid + "_seat", (x - sx / 2, x + sx / 2, 0.405, 0.445,
                                        z - sz / 2, z + sz / 2), "fabric", bevel=0.012)
            table_center_x = min((-3.2, 0, 3.2), key=lambda center: abs(center - x))
            outer = x - sx / 2 if x < table_center_x else x + sx / 2
            bx0, bx1 = (outer, outer + 0.025) if x < table_center_x else (outer - 0.025, outer)
            _box(parts, pid + "_back", (bx0, bx1, 0.445, sy,
                                        z - sz / 2, z + sz / 2), "fabric", bevel=0.005)
            for ix, lx in enumerate((x - sx / 2 + 0.024, x + sx / 2 - 0.024)):
                for iz, lz in enumerate((z - sz / 2 + 0.024, z + sz / 2 - 0.024)):
                    _box(parts, f"{pid}_leg_{ix}_{iz}",
                         (lx - 0.015, lx + 0.015, 0, 0.415,
                          lz - 0.015, lz + 0.015), "bronze")
            continue
        joint = None
        if folder == "21-karate-dojo" and pid == "bag-0":
            joint = "bag-tilt"
        _box(parts, pid, (x - sx / 2, x + sx / 2, y - sy / 2, y + sy / 2,
                          z - sz / 2, z + sz / 2), entry["material"],
             bevel=min(0.012, sx * 0.03, sy * 0.03, sz * 0.03)
             if pid.startswith(("chair-", "table-", "counter", "bench-", "bag-")) else 0,
             joint=joint)
    return parts


def _stairs(parts: list[Part], design: dict) -> None:
    for stair in design.get("stairs", []):
        x0, x1 = stair["x_range_m"]
        for tread in stair["treads"]:
            z0, z1 = tread["z_range_m"]
            top = tread["top_y_m"]
            _box(parts, tread["id"], (x0, x1, top - 0.16, top, z0, z1), "floor-tile")
            _box(parts, tread["id"] + "_nosing", (x0, x1, top, top + 0.005, z0, z0 + 0.025),
                 "stainless")


def _escalators(parts: list[Part], design: dict) -> None:
    for escalator in design.get("escalators", []):
        x = escalator["center_x_m"]
        width = escalator["overall_width_m"]
        profile = escalator["section_profile_zy"]
        for index, ((z0, y0), (z1, y1)) in enumerate(zip(profile, profile[1:])):
            if z1 <= z0:
                continue
            for side in (-1, 1):
                rail_x = x + side * (width / 2 - 0.055)
                # Section rails are stepped to follow the numerical slope.
                segments = max(1, int((z1 - z0) / 0.45))
                for section in range(segments):
                    a = section / segments
                    b = (section + 1) / segments
                    za, zb = z0 + (z1 - z0) * a, z0 + (z1 - z0) * b
                    ya, yb = y0 + (y1 - y0) * a, y0 + (y1 - y0) * b
                    _box(parts, f"{escalator['id']}_rail_{index}_{side}_{section}",
                         (rail_x - 0.035, rail_x + 0.035, min(ya, yb) + 0.78,
                          max(ya, yb) + 0.85, za, zb), "rubber")
            if abs(y1 - y0) > 0.1:
                steps = max(1, int((z1 - z0) / escalator.get("step_pitch_m", 0.4)))
                for step in range(steps):
                    z = z0 + (step + 0.5) * (z1 - z0) / steps
                    y = y0 + (step + 0.5) * (y1 - y0) / steps
                    _box(parts, f"{escalator['id']}_step_{index}_{step}",
                         (x - 0.5, x + 0.5, y - 0.11, y, z - 0.17, z + 0.17), "stainless")


def _entrance(parts: list[Part], design: dict) -> None:
    _stairs(parts, design)
    _escalators(parts, design)
    # Slim canopy posts and a visible route from the street down to the B1 hall.
    for x in (-3.4, 3.4):
        for z in (-11.8, -5.2):
            _box(parts, f"canopy_post_{x}_{z}", (x - 0.055, x + 0.055, 0, 3.25,
                                                z - 0.055, z + 0.055), "stainless")
    _box(parts, "street_landing", (-4, 8, -0.18, 0, -14, -12), "floor-tile")
    _box(parts, "lower_hall_ceiling", (-3.5, 7.5, -3.05, -2.95, 4.08, 14), "paint")
    _box(parts, "lift_cabin", (5.2, 6.8, -6, -3.8, -9.75, -8.25), "stainless",
         joint="lift-cabin")
    _box(parts, "lift_door_left", (5.6, 6.0, -2.1, 0, -7.704, -7.696), "stainless",
         joint="lift-door-left")
    for index in range(9):
        z = -10.5 + index * 2.8
        _box(parts, f"tactile_{index}", (-0.35, 0.35, -6, -5.995, z, z + 0.6), "tactile")
    _box(parts, "closure_shutter", (-3.2, 3.2, 0, 2.6, -12.04, -12.02), "stainless",
         joint="closure-shutter")


def _concourse(parts: list[Part], design: dict) -> None:
    _stairs(parts, design)
    _escalators(parts, design)
    for side in (-1, 1):
        x0, x1 = (-10, -9.8) if side < 0 else (9.8, 10)
        _box(parts, f"side_wall_{side}", (x0, x1,
                                         0, 3.0, -48, 48), "wall-tile")
    _box(parts, "b2_edge_floor_w", (-10, -9.8, -6.3, -6.0, -48, 48), "concrete")
    _box(parts, "b2_edge_floor_e", (9.8, 10, -6.3, -6.0, -48, 48), "concrete")
    for x in (-7.5, 7.5):
        for z in range(-42, 49, 12):
            _box(parts, f"ceiling_light_{x}_{z}", (x - 1.2, x + 1.2, 2.97, 3.0,
                                                   z - 0.12, z + 0.12), "light")
    for index in range(8):
        x = -3.23 + index * 0.88
        _box(parts, f"gate_flap_{index}", (x - 0.28, x + 0.28, 0.52, 0.92,
                                          -28.012, -27.99), "glass",
             joint="gate-flap" if index == 0 else None)
        _box(parts, f"gate_reader_{index}", (x - 0.07, x + 0.07, 1.0, 1.02,
                                            -28.12, -27.88), "dark-display")
    _box(parts, "paid_lift_cabin", (-7.8, -6.2, -5.9, -3.7, 9, 10.5), "stainless",
         joint="paid-lift")
    _box(parts, "staff_door", (-6.25, -6.2, 0, 2.1, -35.4, -34.6), "paint",
         joint="staff-door")
    for z in range(-44, 47, 8):
        _box(parts, f"tactile_guide_{z}", (-0.15, 0.15, 0, 0.005,
                                          z, min(z + 7.5, 47.9)), "tactile")


def _platform(parts: list[Part]) -> None:
    for x in (-10.4, 10.4):
        _box(parts, f"side_wall_{x}", (x - 0.1, x + 0.1, -1.2, 3.6,
                                      -66, 66), "wall-tile")
    for z in range(-60, 61, 6):
        for x in (-4.9, 4.9):
            _box(parts, f"platform_glass_{x}_{z}", (x - 0.012, x + 0.012,
                 0.12, 1.55, z - 2.7, z + 2.7), "glass")
            _box(parts, f"platform_frame_{x}_{z}", (x - 0.035, x + 0.035,
                 0.05, 1.7, z - 2.75, z - 2.70), "stainless")
        _box(parts, f"light_{z}", (-2.5, 2.5, 3.57, 3.6, z - 0.08, z + 0.08), "light")
    for index, z in enumerate((-57.5, 57.5)):
        for x, side in ((-4.9, "west"), (4.9, "east")):
            _box(parts, f"door_leaf_{side}_{index}",
                 (x - 0.012, x + 0.012, 0.1, 1.55, z - 0.38, z + 0.38), "glass",
                 joint="platform-leaf-negative-z" if index == 0 and side == "west" else
                       "platform-leaf-positive-z" if index == 1 and side == "west" else None)
    _box(parts, "emergency_door", (-2.23, -2.22, 0, 1.5, -54.2, -53.8), "stainless",
         joint="emergency-cabinet")


def _venue_shell(parts: list[Part], design: dict, *, dojo: bool) -> None:
    half_x = 5.2
    half_z = 6.2 if dojo else 4.2
    top = 3.5 if dojo else 3.3
    for side in (-1, 1):
        x = side * 5.1
        _box(parts, f"side_wall_{side}", (x - 0.1, x + 0.1, 0, top,
                                         -half_z, half_z), "plaster")
    _box(parts, "rear_wall", (-half_x, half_x, 0, top,
                              -half_z, -half_z + 0.2), "plaster")
    # Shopfront is glazed above a low sill; the opening stays legible from outside.
    _box(parts, "front_sill_w", (-half_x, -0.75, 0, 0.42,
                                 half_z - 0.15, half_z), "paint")
    _box(parts, "front_sill_e", (0.75, half_x, 0, 0.42,
                                 half_z - 0.15, half_z), "paint")
    _box(parts, "front_window_w", (-half_x + 0.2, -0.75, 0.42, 2.85,
                                   half_z - 0.1, half_z - 0.075),
         "frosted-glass" if dojo else "glass")
    _box(parts, "front_window_e", (0.75, half_x - 0.2, 0.42, 2.85,
                                   half_z - 0.1, half_z - 0.075), "glass")
    _box(parts, "front_door_left", (-0.73, -0.015, 0, 2.2,
                                    half_z - 0.08, half_z - 0.055), "glass",
         joint="front-left" if dojo else "entry-left")
    _box(parts, "front_door_right", (0.015, 0.73, 0, 2.2,
                                     half_z - 0.08, half_z - 0.055), "glass")
    for x in (-3.5, 0, 3.5):
        for z in (-3.3, 0.3, 3.3) if dojo else (-2.8, 1.8):
            _box(parts, f"downlight_{x}_{z}", (x - 0.19, x + 0.19,
                                              2.99 if dojo else 2.78,
                                              3.0 if dojo else 2.79,
                                              z - 0.19, z + 0.19), "light")


def _cafe(parts: list[Part], materials: list[Material]) -> None:
    # A separate top veneer gives the primary service counter visible wood grain.
    design = {"materials": [{"id": "oak", "base_color_srgb": "#C5A77A",
                             "roughness": [0.35, 0.46], "metallic": 0}]}
    veneer = replace(materials_for(design)[0], id="oak_veneer")
    materials.append(veneer)
    _box(parts, "counter_wood_veneer", (-1, 4.45, 0.9, 0.908, -1.4, -0.65),
         "oak_veneer", texture_resolution=4096)
    for side, x0, x1 in (("w", -5.2, -5.08), ("e", 5.08, 5.2)):
        _box(parts, f"roof_parapet_{side}", (x0, x1, 3.6, 3.8, -4.2, 4.2), "paint")
    for x in range(-5, 6):
        if x == 5:
            continue
        _box(parts, f"floor_grout_x_{x}", (x - 0.002, x + 0.002,
                                          0, 0.0006, -4.18, 4.18), "bronze")
    for z in range(-4, 5):
        _box(parts, f"floor_grout_z_{z}", (-5.18, 5.18, 0, 0.0006,
                                          z - 0.002, z + 0.002), "bronze")
    for part in list(parts):
        if part.id.startswith("table-") and part.id.endswith("_top"):
            x, _, z = part.transform.translation
            _box(parts, "grain_" + part.id, (x - 0.39, x + 0.39, 0.720, 0.721,
                                          z - 0.34, z + 0.34), "oak_veneer",
                 texture_resolution=2048)
    _box(parts, "rear_door", (-3.6, -2.8, 0, 2.1, -4.19, -4.16), "paint",
         joint="rear-door")
    _box(parts, "wc_door", (-4.45, -4.4, 0, 2.0, -1.85, -1.05), "paint",
         joint="wc-door")
    _box(parts, "fridge_door", (4.88, 4.9, 0, 1.8, -2.95, -2.25), "stainless",
         joint="fridge-door")
    _box(parts, "oven_door", (0.35, 0.95, 0.85, 1.3, -3.38, -3.36), "glass",
         joint="oven-door")
    _box(parts, "grinder_dial", (1.98, 2.02, 1.2, 1.29, -0.86, -0.84), "bronze",
         joint="grinder-dial")


def _dojo(parts: list[Part], materials: list[Material]) -> None:
    design = {"materials": [{"id": "eva-blue", "base_color_srgb": "#648294",
                             "roughness": [0.68, 0.77], "metallic": 0}]}
    materials.append(replace(materials_for(design)[0], id="mat_texture"))
    for ix, iz in ((2, 2), (3, 2), (4, 2), (3, 3)):
        x, z = ix - 3.5, iz - 4.5
        _box(parts, f"mat_grain_{ix}_{iz}", (x - 0.48, x + 0.48,
                                            0.024, 0.025, z - 0.48, z + 0.48),
             "mat_texture", texture_resolution=2048)
    for x in (-4, 4):
        _box(parts, f"mat_ramp_{x}", (x - 0.1, x + 0.1, 0, 0.025,
                                     -5, 2), "eva-charcoal")
    for z in (-5, 2):
        _box(parts, f"mat_ramp_{z}", (-4, 4, 0, 0.025,
                                     z - 0.1, z + 0.1), "eva-charcoal")
    for x in range(-3, 4):
        _box(parts, f"mat_seam_x_{x}", (x - 0.001, x + 0.001,
                                       0.025, 0.0252, -5, 2), "rubber")
    for z in range(-4, 2):
        _box(parts, f"mat_seam_z_{z}", (-4, 4, 0.025, 0.0252,
                                       z - 0.001, z + 0.001), "rubber")
    for name, bounds, joint in (
        ("training_door", (-0.78, 0, 0, 2.2, 2.94, 2.96), "training-left"),
        ("changing_door", (-1.46, -1.44, 0, 2, 3.1, 3.9), "changing-door"),
        ("wc_door", (3.7, 4.5, 0, 2, 3.99, 4.01), "wc-door"),
        ("office_door", (1.9, 2.7, 0, 2, 3.99, 4.01), "office-door"),
        ("rear_exit", (-0.8, 0, 0, 2.1, -6.19, -6.16), "rear-exit"),
    ):
        _box(parts, name, bounds, "paint", joint=joint)
    for i in range(6):
        z = 3.14 + i * 0.45
        _box(parts, f"locker_door_{i}", (-4.456, -4.444, 0.1, 1.75,
                                         z, z + 0.41), "paint",
             joint=f"locker-{i}-door")
    for i, z in enumerate((-3, 0.3)):
        _box(parts, f"bag_strap_{i}", (-4.5, -4.4, 1.67, 2.15,
                                      z - 0.08, z + 0.08), "stainless")


def build_space(design: dict, folder: str) -> Asset:
    materials = list(materials_for(design, include_surface_maps=False))
    parts = _scheduled_parts(design, folder)
    if folder == "17-subway-entrance":
        _entrance(parts, design)
    elif folder == "18-subway-concourse":
        _concourse(parts, design)
    elif folder == "19-subway-platform":
        _platform(parts)
    else:
        _venue_shell(parts, design, dojo=folder == "21-karate-dojo")
        if folder == "20-cafe":
            _cafe(parts, materials)
        else:
            _dojo(parts, materials)
    rig, poses, clips = rig_for(design, folder)
    return Asset(name=design["id"], materials=tuple(materials), parts=tuple(parts),
                 rig=rig, poses=poses, clips=clips)
