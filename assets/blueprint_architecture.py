"""Standalone 02–04 buildings assembled from the same templates used by the city."""

from __future__ import annotations

from dataclasses import replace

from promodeler.core import Array, Asset, Box, Bricks, ColorRamp, Layer, Material, Noise, Part, Transform, srgb

from assets.blueprint_materials import materials_for
from assets.blueprint_props import joint_id, rig_for
from assets.city import apartment, box, city_materials, convenience, office


PREFIX = "site_standalone_"


def part_map_for(folder: str) -> dict[str, tuple[str, ...]]:
    p = PREFIX
    if folder == "02-apartment":
        return {
            "body": (p + "slabs", p + "roof", p + "side_w"),
            "balcony": (p + "balconies", p + "balcony_support_w", p + "balcony_support_e"),
            "corridor": (p + "corridors", p + "corridor_support_w", p + "corridor_support_e"),
            "stair-west": (p + "stair_w_outside", p + "stair_w_inside", p + "stair_w_back",
                           p + "stair_w_landings"),
            "stair-east": (p + "stair_e_outside", p + "stair_e_inside", p + "stair_e_back",
                           p + "stair_e_landings"),
        }
    if folder == "03-convenience":
        return {
            "checkout": (p + "checkout",),
            "cold-wall": (p + "cold_wall",),
            **{f"shelf-{i}": (p + f"shelf_{i}_boards", p + f"shelf_{i}_left",
                                p + f"shelf_{i}_right") for i in range(3)},
        }
    return {
        "envelope": (p + "floor_ground", p + "roof_screen", p + "south_glass_ground"),
        "facade-module": ("facade_module_sample",),
        "roof-screen": (p + "roof_screen",),
    }


def _focal_tile() -> Material:
    base = srgb(0.81, 0.8, 0.76)
    variation = Noise(size=0.095, detail=1, seed=204)
    joints = Bricks(width=0.095, height=0.045, mortar=0.005, offset=0.5, axis="y")
    return Material("tile_detail", base_color=ColorRamp(variation, (
        (0.25, base.scaled(0.97)), (0.75, base.scaled(1.03)))),
        roughness=0.46, height=-joints * 0.002,
        layers=(Layer(base_color=base.scaled(0.72), mask=joints),), bump_strength=1.0)


def build_architecture(design: dict, folder: str) -> Asset:
    parts: list[Part] = []
    placement = {"id": "standalone", "position_m": [0, 0, 0], "yaw_rad": 0}
    {"02-apartment": apartment, "03-convenience": convenience, "04-office": office}[folder](parts, placement)
    # The city templates include site parking; the standalone blueprint covers
    # only the building envelope and starts at ground level.
    excluded = ("_foundation", "_parking", "_parking_stripes", "_lot", "_lot_stripes", "_plaza", "_loading")
    parts = [part for part in parts if not part.id.endswith(excluded)]
    existing = {material.id: material for material in city_materials()}
    for material in materials_for(design, include_surface_maps=False):
        existing.setdefault(material.id, material)
    existing["tile_detail"] = _focal_tile()

    if folder == "02-apartment":
        for side, x0, x1 in (("w", -12, -11.85), ("e", 11.85, 12)):
            box(parts, PREFIX + f"balcony_support_{side}", (x0, x1, 0, 18, 8.35, 8.5), "concrete")
            box(parts, PREFIX + f"corridor_support_{side}", (x0, x1, 0, 18, -8.8, -8.65), "concrete")
        # Existing partition walls become wallpaper-lined interiors.  Floor
        # panels and a reception counter give the lobby a distinct material.
        parts = [replace(part, material="wallpaper") if "party_wall" in part.id else part for part in parts]
        for floor in range(6):
            y = floor * 3 + 0.21
            for bay in range(4):
                if floor == 0 and bay in (1, 2):
                    continue
                x0 = -12 + bay * 6
                box(parts, f"unit_floor_{floor}_{bay}", (x0 + 0.1, x0 + 5.9, y, y + 0.012,
                                                         -4.2, 6.7), "wood")
        box(parts, "lobby_reception", (-2.2, 2.2, 0.2, 1.12, -1.2, -0.55), "wood")
        box(parts, "detail_tile_entrance", (-3.5, -1.5, 0.2, 2.3, 7.0, 7.012),
            "tile_detail")
        parts[-1] = replace(parts[-1], texture_resolution=2048)
        box(parts, "elevator_cabin", (-1.0, 1.0, 0, 2.3, -6.8, -4.9), "metal")
        parts[-1] = replace(parts[-1], parent_joint=joint_id("elevator"))
        parts = [replace(part, parent_joint=joint_id("entry-door"))
                 if part.id == PREFIX + "lobby_glass" else part for part in parts]
    elif folder == "03-convenience":
        box(parts, "detail_tile_entry", (-1.5, 1.5, 0.06, 0.068, 3.0, 5.8), "tile_detail")
        parts[-1] = replace(parts[-1], texture_resolution=4096)
        box(parts, "delivery_door", (5.9, 7.1, 0, 2.1, -5.99, -5.94), "paint")
        parts[-1] = replace(parts[-1], parent_joint=joint_id("delivery"))
        parts = [replace(part, parent_joint=joint_id("entry-left"))
                 if part.id == PREFIX + "entry_left" else part for part in parts]
    else:
        box(parts, "facade_module_sample", (-0.03, 0.03, 0, 3.6, 8.925, 9.075), "metal")
        box(parts, "lobby_stone_inlay", (-2, 2, 0.25, 0.258, 5.0, 8.5), "tile_detail")
        parts[-1] = replace(parts[-1], texture_resolution=4096)
        box(parts, "lift_cabin", (-1.9, -0.3, 0, 2.8, -8.7, -6.0), "metal")
        parts[-1] = replace(parts[-1], parent_joint=joint_id("lift-cabin"))
        box(parts, "stair_door", (-8.9, -8.0, 0, 2.1, -3.04, -3.0), "paint")
        parts[-1] = replace(parts[-1], parent_joint=joint_id("stair-door"))
        parts = [replace(part, parent_joint=joint_id("lobby-entry"))
                 if part.id == PREFIX + "lobby_entry" else part for part in parts]
    rig, poses, clips = rig_for(design, folder)
    return Asset(name=design["id"], materials=tuple(existing.values()), parts=tuple(parts),
                 rig=rig, poses=poses, clips=clips)
