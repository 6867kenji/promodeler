"""Independent 1K apartment room (blueprints/japan-realistic-v1/06-room), structure v0.

Built from the blueprint's zone rectangles, opening schedule, motion
schedule and fixture envelopes: slabs, exterior walls, partitions, floor
finishes, baseboards, the south sash, the entry and toilet doors, sliding
living and storage doors, fixed kitchen, tub, vanity, toilet and outlet,
and the balcony with its railing. Movable fittings are joints with an
``open`` pose and an ``open-close`` clip. No furniture or appliances.

Assumptions not in the schedule: the connector zone is an open passage
into the living room and into the wash room; the bath and wash openings
have no door leaf.

Run:  python -m promodeler build assets/room.py --texture-resolution 512 --bake-samples 8
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from promodeler.core import (
    Array, Asset, AssetGenerator, Bevel, Boolean, Box, Bricks, Camera, Clip, ColorRamp, Cutter, Cylinder, GenerationInput,
    Joint, JointTransform, Keyframe, Layer, Light, Material, ModelingError, Noise, Part, Pose, RenderSettings, Rig,
    Transform, presets, srgb,
)

# --- blueprint numbers (06-room/blueprint.json) ------------------------------
CLEAR_X = (-2.5, 2.5)
CLEAR_Z = (-3.5, 3.5)
CEILING = 2.4
OUTER = 0.15
PARTITION = 0.1
SLAB = 0.15
FINISH = 0.012
BALCONY_DEPTH = 1.2
ENTRY_DROP = 0.05


@dataclass(frozen=True)
class RoomParameters:
    door_open: float = 1.0  # 0..1 fraction of each motion range used by the "open" pose


def validate(p: RoomParameters) -> None:
    if not 0.0 <= p.door_open <= 1.0:
        raise ModelingError("room.doorOpen", "door_open must be within 0...1.")


def box_part(part_id: str, x0: float, x1: float, y0: float, y1: float, z0: float, z1: float, material: str,
             cutters=(), parent_joint: str | None = None, smooth: float | None = None,
             bevel: float = 0.0, texture_resolution: int | None = None) -> Part:
    """An axis-aligned box from its extents, with optional difference cutters given in the same coordinates."""
    center = ((x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2)
    size = (abs(x1 - x0), abs(y1 - y0), abs(z1 - z0))
    modifiers = []
    for cx0, cx1, cy0, cy1, cz0, cz1 in cutters:
        local = ((cx0 + cx1) / 2 - center[0], (cy0 + cy1) / 2 - center[1], (cz0 + cz1) / 2 - center[2])
        modifiers.append(Boolean("difference", cutter=Cutter(
            shape=Box(size=(abs(cx1 - cx0), abs(cy1 - cy0), abs(cz1 - cz0))), transform=Transform(translation=local))))
    if bevel:
        modifiers.append(Bevel(width=bevel, segments=3))
    return Part(id=part_id, shape=Box(size=size), material=material, transform=Transform(translation=center),
                modifiers=tuple(modifiers), parent_joint=parent_joint, smooth_angle=smooth,
                texture_resolution=texture_resolution)


def opening_cutter_x(cx: float, width: float, height: float, sill: float, z0: float, z1: float):
    """Opening in a wall that runs along X (thin in Z)."""
    return (cx - width / 2, cx + width / 2, sill - 0.01, sill + height, z0 - 0.02, z1 + 0.02)


def opening_cutter_z(cz: float, width: float, height: float, sill: float, x0: float, x1: float):
    """Opening in a wall that runs along Z (thin in X)."""
    return (x0 - 0.02, x1 + 0.02, sill - 0.01, sill + height, cz - width / 2, cz + width / 2)


def build(input: GenerationInput) -> Asset:
    p: RoomParameters = input.parameters
    seed = input.seed
    x0, x1 = CLEAR_X
    z0, z1 = CLEAR_Z

    # --- materials ---------------------------------------------------------------
    plank_seams = Bricks(width=0.09, height=0.9, mortar=0.0008, offset=0.5, offset_frequency=2, axis="y")
    grain = Noise(size=(0.003, 0.003, 0.5), detail=4.0, roughness=0.55, seed=seed)
    plank_tone = Noise(size=(0.09, 0.09, 1.8), detail=1.0, roughness=0.3, seed=seed + 1)
    oak = srgb(0.784, 0.671, 0.502)
    wood = Material(
        "wood",
        base_color=ColorRamp(plank_tone * 0.6 + grain * 0.4, ((0.15, oak.scaled(0.8)), (0.5, oak), (0.9, oak.scaled(1.1)))),
        roughness=0.36 + grain * 0.12,
        height=-plank_seams * 0.0008 + grain * 0.00005,
        layers=(Layer(base_color=oak.scaled(0.72), roughness=0.5, mask=plank_seams),),
        bump_strength=1.5,
    )
    wallpaper = Material("wallpaper", base_color=srgb(0.933, 0.925, 0.898), roughness=0.84)
    paint = Material("paint", base_color=srgb(0.898, 0.894, 0.855), roughness=0.55)
    ceiling_paint = Material("ceiling", base_color=srgb(0.95, 0.95, 0.94), roughness=0.8)
    concrete = presets.concrete("concrete", color=srgb(0.6, 0.59, 0.56), seed=seed, staining=0.3)
    metal = Material("metal", base_color=srgb(0.27, 0.286, 0.29), metallic=1.0, roughness=0.34)
    brushed_metal = presets.brushed_metal("brushed_metal", color=srgb(0.27, 0.286, 0.29),
                                          seed=seed, edge_radius=0.003)
    glass = Material("glass", base_color=srgb(0.843, 0.886, 0.878, 0.3), roughness=0.05, alpha_mode="blend")
    mirror = Material("mirror", base_color=srgb(0.82, 0.85, 0.86), metallic=1.0, roughness=0.04)
    gasket = Material("gasket", base_color=srgb(0.08, 0.09, 0.09), roughness=0.7)
    hob = Material("hob", base_color=srgb(0.12, 0.13, 0.14), metallic=0.25, roughness=0.28)
    tile_grid = Bricks(width=0.3, height=0.3, mortar=0.003, offset=0.0, axis="y")
    tile = Material(
        "tile", base_color=ColorRamp(Noise(size=0.3, detail=1.0, seed=seed + 4), ((0.3, srgb(0.82, 0.8, 0.76)), (0.7, srgb(0.86, 0.84, 0.8)))),
        roughness=0.45 + Noise(size=0.002, detail=2.0, seed=seed + 5) * 0.1, height=-tile_grid * 0.002,
        layers=(Layer(base_color=srgb(0.62, 0.6, 0.57), roughness=0.9, mask=tile_grid),), bump_strength=1.2,
    )
    tile_trim = Material("tile_trim", base_color=srgb(0.84, 0.82, 0.78), roughness=0.48)
    entry_tile = Material(
        "entry_tile", base_color=srgb(0.5, 0.49, 0.47), roughness=0.5,
        height=-Bricks(width=0.3, height=0.3, mortar=0.003, offset=0.0, axis="y") * 0.002,
        layers=(Layer(base_color=srgb(0.36, 0.35, 0.34), mask=Bricks(width=0.3, height=0.3, mortar=0.003, offset=0.0, axis="y")),),
    )
    exterior_x = Material(
        "exterior_x", base_color=srgb(0.843, 0.827, 0.784), roughness=0.5,
        height=-Bricks(width=0.095, height=0.045, mortar=0.005, offset=0.5, axis="x") * 0.002,
        layers=(Layer(base_color=srgb(0.7, 0.69, 0.66), roughness=0.9, mask=Bricks(width=0.095, height=0.045, mortar=0.005, offset=0.5, axis="x")),),
    )
    materials = (wood, wallpaper, paint, ceiling_paint, concrete, metal, brushed_metal,
                 glass, mirror, gasket, hob,
                 tile, tile_trim, entry_tile, exterior_x)

    parts: list[Part] = []

    # --- slabs -------------------------------------------------------------------
    ex0, ex1 = x0 - OUTER, x1 + OUTER
    ez0, ez1 = z0 - OUTER, z1 + OUTER
    parts.append(box_part("floor_slab", ex0, ex1, -SLAB, -FINISH, ez0, ez1, "concrete"))
    parts.append(box_part("ceiling_slab", ex0, ex1, CEILING, CEILING + SLAB, ez0, ez1, "ceiling"))

    # --- exterior walls with the entry and the south sash --------------------------
    parts.append(box_part("wall_north", x0, x1, 0.0, CEILING, ez0, z0, "wallpaper",
                          cutters=[opening_cutter_x(1.4, 0.85, 2.1, -ENTRY_DROP, ez0, z0)], texture_resolution=2048))
    parts.append(box_part("wall_south", x0, x1, 0.0, CEILING, z1, ez1, "wallpaper",
                          cutters=[opening_cutter_x(0.0, 2.4, 2.1, 0.0, z1, ez1)], texture_resolution=2048))
    parts.append(box_part("wall_east", x1, ex1, 0.0, CEILING, ez0, ez1, "wallpaper", texture_resolution=2048))
    parts.append(box_part("wall_west", ex0, x0, 0.0, CEILING, ez0, ez1, "wallpaper", texture_resolution=2048))

    # --- partitions ------------------------------------------------------------------
    living_wall_z = (-0.4, -0.3)
    living_openings = [  # (center x, width): toilet door, storage doors, connector passage, living door
        (-2.0, 0.65), (-0.8, 1.2), (0.25, 0.7), (1.1, 0.8),
    ]
    parts.append(box_part("wall_living_north", x0, x1, 0.0, CEILING, *living_wall_z, "wallpaper",
                          cutters=[opening_cutter_x(cx, w, 2.0, 0.0, *living_wall_z) for cx, w in living_openings]))
    parts.append(box_part("wall_service_south", x0, 0.6, 0.0, CEILING, -1.5, -1.4, "wallpaper",
                          cutters=[opening_cutter_x(0.2, 0.6, 2.0, 0.0, -1.5, -1.4)]))
    parts.append(box_part("wall_bath_wash", -0.8, -0.7, 0.0, CEILING, z0, -1.5, "wallpaper",
                          cutters=[opening_cutter_z(-2.0, 0.65, 2.0, 0.0, -0.8, -0.7)]))
    parts.append(box_part("wall_wash_east", 0.5, 0.6, 0.0, CEILING, z0, -1.5, "wallpaper",
                          cutters=[opening_cutter_z(-2.4, 0.65, 2.0, 0.0, 0.5, 0.6)]))
    parts.append(box_part("wall_toilet_east", -1.5, -1.4, 0.0, CEILING, -1.4, -0.4, "wallpaper"))
    parts.append(box_part("wall_storage_east", -0.2, -0.1, 0.0, CEILING, -1.4, -0.4, "wallpaper"))

    # --- floor finishes (top at y = 0; the entry is dropped 50 mm) ------------------
    parts.append(box_part("floor_living", x0, x1, -FINISH, 0.0, -0.3, z1, "wood", texture_resolution=4096))
    parts.append(box_part("floor_hall", 0.6, x1, -FINISH, 0.0, -2.6, -0.4, "wood", texture_resolution=2048))
    parts.append(box_part("floor_entry", 0.6, x1, -FINISH - ENTRY_DROP, -ENTRY_DROP, z0, -2.6, "entry_tile"))
    parts.append(box_part("floor_connector", -0.1, 0.6, -FINISH, 0.0, -1.4, -0.4, "wood", texture_resolution=1024))
    parts.append(box_part("floor_storage", -1.4, -0.2, -FINISH, 0.0, -1.4, -0.4, "wood", texture_resolution=2048))
    parts.append(box_part("floor_wash", -0.7, 0.5, -FINISH, 0.0, z0, -1.5, "tile", texture_resolution=2048))
    parts.append(Part(id="floor_bath", shape=Box(size=(1.7, FINISH, 2.0)), material="tile",
                      transform=Transform(translation=(-1.65, -FINISH / 2, -2.5), rotation=(math.atan(0.01), 0.0, 0.0)),
                      texture_resolution=2048))
    parts.append(box_part("floor_toilet", x0, -1.5, -FINISH, 0.0, -1.4, -0.4, "tile", texture_resolution=2048))
    parts.append(box_part("bath_upstand_north", x0, -0.8, 0.0, 0.1, z0, z0 + 0.012, "tile_trim"))
    parts.append(box_part("bath_upstand_south", x0, -0.8, 0.0, 0.1, -1.512, -1.5, "tile_trim"))
    parts.append(box_part("bath_upstand_west", x0, x0 + 0.012, 0.0, 0.1, z0, -1.5, "tile_trim"))

    # --- baseboards in the living room (60 x 7 mm) -----------------------------------
    bb_h, bb_t = 0.06, 0.007
    parts.append(box_part("baseboard_west", x0, x0 + bb_t, 0.0, bb_h, -0.3, z1, "paint"))
    parts.append(box_part("baseboard_east", x1 - bb_t, x1, 0.0, bb_h, -0.3, z1, "paint"))
    parts.append(box_part("baseboard_south_w", x0, -1.2, 0.0, bb_h, z1 - bb_t, z1, "paint"))
    parts.append(box_part("baseboard_south_e", 1.2, x1, 0.0, bb_h, z1 - bb_t, z1, "paint"))
    piers = [(x0, -2.325), (-1.675, -1.4), (-0.2, -0.1), (0.6, 0.7), (1.5, x1)]
    for index, (px0, px1) in enumerate(piers):
        parts.append(box_part(f"baseboard_north_{index}", px0, px1, 0.0, bb_h, -0.3, -0.3 + bb_t, "paint"))

    # --- south sash: frame, two sliding panels (left panel is movable) ----------------
    sz0, sz1 = z1, ez1
    parts.append(box_part("sash_sill", -1.2, 1.2, 0.0, 0.05, sz0, sz1, "metal"))
    parts.append(box_part("sash_head", -1.2, 1.2, 2.05, 2.1, sz0, sz1, "metal"))
    parts.append(box_part("sash_jamb_w", -1.2, -1.15, 0.05, 2.05, sz0, sz1, "metal"))
    parts.append(box_part("sash_jamb_e", 1.15, 1.2, 0.05, 2.05, sz0, sz1, "metal"))
    for name, px0, px1, pz0, pz1, joint in (("left", -1.2, 0.02, 3.53, 3.565, "j_sash_left"), ("right", -0.02, 1.2, 3.585, 3.62, None)):
        parts.append(box_part(f"sash_{name}_frame", px0, px1, 0.05, 2.05, pz0, pz1, "metal",
                              cutters=[(px0 + 0.04, px1 - 0.04, 0.09, 2.01, pz0 - 0.02, pz1 + 0.02)], parent_joint=joint))
        gz = (pz0 + pz1) / 2
        parts.append(box_part(f"sash_{name}_glass", px0 + 0.04, px1 - 0.04, 0.09, 2.01, gz - 0.003, gz + 0.003, "glass",
                              parent_joint=joint))
        for side, edge in (("w", px0 + 0.041), ("e", px1 - 0.041)):
            parts.append(box_part(f"sash_{name}_gasket_{side}", edge - 0.002, edge + 0.002, 0.09, 2.01,
                                  gz - 0.004, gz + 0.004, "gasket", parent_joint=joint))
    for index, track_z in enumerate((3.547, 3.602)):
        parts.append(box_part(f"sash_track_{index}", -1.16, 1.16, 0.05, 0.057,
                              track_z - 0.004, track_z + 0.004, "metal", bevel=0.001))

    # --- doors ------------------------------------------------------------------------
    parts.append(box_part("door_entry", 0.975, 1.825, -ENTRY_DROP, 2.05, -3.595, -3.555, "paint",
                          parent_joint="j_entry", bevel=0.002))
    parts.append(box_part("door_entry_handle", 1.74, 1.77, 0.95, 1.05, -3.555, -3.515, "metal", parent_joint="j_entry"))
    parts.append(box_part("door_entry_lock", 1.745, 1.765, 1.13, 1.17, -3.555, -3.535, "metal", parent_joint="j_entry"))
    parts.append(box_part("door_toilet", -2.325, -1.675, 0.0, 2.0, -0.37, -0.33, "paint", parent_joint="j_toilet"))
    parts.append(box_part("door_living", 0.7, 1.5, 0.0, 2.0, -0.37, -0.335, "paint", parent_joint="j_living"))
    parts.append(box_part("door_storage_left", -1.4, -0.8, 0.0, 2.0, -0.375, -0.355, "paint", parent_joint="j_storage"))
    parts.append(box_part("door_storage_right", -0.8, -0.2, 0.0, 2.0, -0.345, -0.325, "paint"))
    for index, hinge_y in enumerate((0.35, 1.05, 1.75)):
        parts.append(Part(id=f"door_entry_hinge_{index}", shape=Cylinder(radius=0.004, height=0.045, segments=16),
                          material="metal", transform=Transform(translation=(0.975, hinge_y, -3.552)),
                          parent_joint="j_entry", smooth_angle=math.radians(40)))

    # --- fixed fixtures -----------------------------------------------------------------
    parts.append(box_part("kitchen_base", 1.85, 2.5, 0.0, 0.82, -2.7, -0.6, "paint", bevel=0.003))
    parts.append(box_part("kitchen_top", 1.85, 2.5, 0.82, 0.85, -2.7, -0.6, "brushed_metal",
                          cutters=[(1.95, 2.4, 0.83, 0.87, -2.5, -1.9)]))
    parts.append(box_part("kitchen_sink", 1.95, 2.4, 0.66, 0.83, -2.5, -1.9, "brushed_metal",
                          cutters=[(1.96, 2.39, 0.67, 0.86, -2.49, -1.91)], bevel=0.004))
    for index, (cz0, cz1) in enumerate(((-2.66, -1.95), (-1.94, -1.28), (-1.27, -0.64))):
        parts.append(box_part(f"kitchen_cabinet_front_{index}", 1.842, 1.851, 0.08, 0.77,
                              cz0, cz1, "paint", bevel=0.002))
        parts.append(box_part(f"kitchen_cabinet_handle_{index}", 1.829, 1.842, 0.61, 0.625,
                              (cz0 + cz1) / 2 - 0.09, (cz0 + cz1) / 2 + 0.09, "metal", bevel=0.002))
    parts.append(Part(id="kitchen_faucet_stem", shape=Cylinder(radius=0.012, height=0.22, segments=24),
                      material="metal", transform=Transform(translation=(2.28, 0.96, -2.2)),
                      smooth_angle=math.radians(40)))
    parts.append(box_part("kitchen_faucet_spout", 2.12, 2.29, 1.055, 1.075, -2.21, -2.19,
                          "metal", bevel=0.006))
    for index, burner_z in enumerate((-1.26, -0.86)):
        parts.append(Part(id=f"kitchen_hob_burner_{index}", shape=Cylinder(radius=0.105, height=0.006, segments=48),
                          material="hob", transform=Transform(translation=(2.18, 0.853, burner_z)),
                          smooth_angle=math.radians(40)))
    parts.append(box_part("kitchen_range_hood", 1.88, 2.48, 1.96, 2.08, -1.48, -0.66,
                          "metal", bevel=0.008))
    parts.append(box_part("tub", -2.4, -0.9, 0.0, 0.56, -3.3, -2.5, "paint",
                          cutters=[(-2.35, -0.95, 0.06, 0.6, -3.25, -2.55)], bevel=0.012))
    parts.append(box_part("vanity", -0.4, 0.2, 0.0, 0.8, -3.45, -2.95, "paint",
                          cutters=[(-0.325, 0.125, 0.66, 0.84, -3.4, -3.05)], bevel=0.008))
    parts.append(Part(id="vanity_faucet_stem", shape=Cylinder(radius=0.009, height=0.12, segments=20),
                      material="metal", transform=Transform(translation=(-0.1, 0.86, -3.37))))
    parts.append(box_part("vanity_mirror", -0.35, 0.15, 0.95, 1.75, -3.49, -3.48,
                          "mirror", bevel=0.002))
    parts.append(box_part("toilet_tank", -2.19, -1.81, 0.4, 0.76, -1.275, -1.095, "paint"))
    parts.append(Part(id="toilet_bowl", shape=Cylinder(radius=0.18, height=0.38, segments=32), material="paint",
                      transform=Transform(translation=(-2.0, 0.19, -0.855), scale=(1.0, 1.0, 1.3)),
                      modifiers=(Boolean("difference", cutter=Cutter(shape=Cylinder(radius=0.13, height=0.3, segments=32),
                                                                       transform=Transform(translation=(0.0, 0.18, 0.0)))),
                                 Bevel(width=0.008, segments=3)), smooth_angle=math.radians(40)))
    parts.append(Part(id="toilet_seat", shape=Cylinder(radius=0.174, height=0.018, segments=32), material="paint",
                      transform=Transform(translation=(-2.0, 0.386, -0.855), scale=(1.0, 1.0, 1.28)),
                      modifiers=(Boolean("difference", cutter=Cutter(shape=Cylinder(radius=0.13, height=0.04, segments=32))),),
                      smooth_angle=math.radians(40)))
    parts.append(Part(id="toilet_flush_button", shape=Cylinder(radius=0.025, height=0.006, segments=24),
                      material="metal", transform=Transform(translation=(-2.0, 0.764, -1.18))))
    parts.append(box_part("outlet", 2.484, 2.496, 0.24, 0.36, 1.465, 1.535, "paint"))
    parts.append(box_part("wall_switch", 2.486, 2.498, 1.14, 1.26, 1.46, 1.54, "paint", bevel=0.002))
    parts.append(box_part("bath_vent", -1.9, -1.5, 2.386, 2.399, -3.25, -3.05,
                          "paint", bevel=0.003))
    parts.append(Part(id="bath_drain", shape=Cylinder(radius=0.025, height=0.003, segments=24),
                      material="metal", transform=Transform(translation=(-2.25, 0.001, -1.65))))

    # --- balcony ------------------------------------------------------------------------
    bz0, bz1 = ez1, ez1 + BALCONY_DEPTH
    parts.append(Part(id="balcony_slab", shape=Box(size=(ex1 - ex0, SLAB - 0.02, bz1 - bz0)), material="concrete",
                      transform=Transform(translation=(0.0, (-SLAB - 0.02) / 2, (bz0 + bz1) / 2),
                                          rotation=(math.atan(0.01), 0.0, 0.0)), texture_resolution=4096))
    parts.append(box_part("balcony_wall_w", ex0, x0, -0.02, 1.1, bz0, bz1, "exterior_x", texture_resolution=2048))
    parts.append(box_part("balcony_wall_e", x1, ex1, -0.02, 1.1, bz0, bz1, "exterior_x", texture_resolution=2048))
    parts.append(box_part("railing_top", x0, x1, 1.05, 1.1, bz1 - 0.05, bz1, "metal"))
    parts.append(box_part("railing_bottom", x0, x1, 0.08, 0.12, bz1 - 0.05, bz1, "metal"))
    parts.append(Part(id="railing_bars", shape=Cylinder(radius=0.008, height=0.93, segments=12), material="metal",
                      transform=Transform(translation=(-2.4, 0.585, bz1 - 0.025)),
                      modifiers=(Array(count=25, offset=(0.2, 0.0, 0.0)),), smooth_angle=math.radians(40)))
    parts.append(Part(id="balcony_drain", shape=Cylinder(radius=0.025, height=0.003, segments=24),
                      material="metal", transform=Transform(translation=(2.15, -0.018, bz1 - 0.25))))

    # --- movable fittings as joints ---------------------------------------------------------
    rig = Rig("room", joints=(
        Joint("j_entry", head=(0.975, 0.0, -3.575), tail=(0.975, 1.0, -3.575)),
        Joint("j_toilet", head=(-2.325, 0.0, -0.35), tail=(-2.325, 1.0, -0.35)),
        Joint("j_living", head=(0.7, 0.0, -0.35), tail=(0.7, 1.0, -0.35)),
        Joint("j_sash_left", head=(-0.6, 0.0, 3.575), tail=(-0.6, 1.0, 3.575)),
        Joint("j_storage", head=(-1.1, 0.0, -0.35), tail=(-1.1, 1.0, -0.35)),
    ))
    k = p.door_open
    open_pose = Pose("open", {
        "j_entry": JointTransform(rotation=(0.0, math.radians(100) * k, 0.0), space="world"),      # outward, to the north
        "j_toilet": JointTransform(rotation=(0.0, math.radians(-90) * k, 0.0), space="world"),     # into the living room
        "j_living": JointTransform(translation=(0.8 * k, 0.0, 0.0), space="world"),
        "j_sash_left": JointTransform(translation=(1.1 * k, 0.0, 0.0), space="world"),
        "j_storage": JointTransform(translation=(0.55 * k, 0.0, 0.0), space="world"),
    })
    clips = (Clip("open-close", duration=4.0, loop=False,
                  keyframes=(Keyframe(0.0, None), Keyframe(2.0, "open"), Keyframe(4.0, None))),)

    return Asset(name="Room", materials=materials, parts=tuple(parts), rig=rig, poses=(open_pose,), clips=clips)


asset = AssetGenerator(name="Room", parameters=RoomParameters(), build=build, validate=validate, seed=6)
blueprint = "../blueprints/japan-realistic-v1/06-room/blueprint.json"
blueprint_part_map = {
    "kitchen": ("kitchen_base", "kitchen_top", "kitchen_sink"),
    "vanity": ("vanity",),
    "toilet-bowl": ("toilet_bowl", "toilet_tank"),
}
blueprint_motion_map = {
    "entrance": "j_entry", "living": "j_living", "balcony-left": "j_sash_left",
    "storage": "j_storage", "toilet-door": "j_toilet",
}
blueprint_required_parts = (
    "sash_track_0", "sash_track_1", "sash_left_gasket_w", "door_entry_hinge_0",
    "kitchen_cabinet_front_0", "kitchen_faucet_stem", "kitchen_hob_burner_0",
    "kitchen_range_hood", "vanity_mirror", "wall_switch", "bath_vent", "bath_drain", "balcony_drain",
    "bath_upstand_north", "bath_upstand_south", "bath_upstand_west",
)
blueprint_texel_parts = (
    "floor_living", "floor_hall", "floor_entry", "floor_connector", "floor_storage",
    "floor_wash", "floor_bath", "floor_toilet", "balcony_slab", "balcony_wall_w", "balcony_wall_e",
)
render = RenderSettings(
    resolution=768,
    aspect_ratio=1.6,
    views=("perspective",),
    passes=("shaded",),
    cameras=(
        Camera("interior_north", position=(0.0, 1.5, 3.2), target=(1.2, 1.1, -2.3), fov=math.radians(75),
               hide_parts=("door_living",)),
        Camera("entry_hall", position=(1.55, 1.5, -0.5), target=(1.4, 1.05, -3.6), fov=math.radians(70)),
        Camera("east_section", position=(4.0, 1.2, 0.0), target=(0.0, 1.2, 0.0), orthographic=True, ortho_scale=9.2,
               clip_start=0.001, hide_parts=("wall_east", "balcony_wall_e")),
        Camera("dollhouse", position=(5.0, 12.0, 6.0), target=(0.0, 0.6, 0.6), fov=math.radians(50),
               hide_parts=("ceiling_slab",)),
    ),
    lights=(
        Light("living", position=(0.0, 2.3, 1.6), energy=80.0, size=1.2),
        Light("hall", position=(1.55, 2.3, -2.0), energy=35.0, size=0.6),
        Light("wash", position=(-0.1, 2.3, -2.5), energy=15.0, size=0.4),
        Light("bath", position=(-1.65, 2.3, -2.5), energy=15.0, size=0.4),
        Light("toilet", position=(-2.0, 2.3, -0.9), energy=8.0, size=0.3),
    ),
)
