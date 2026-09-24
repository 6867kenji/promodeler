"""Shiomi 500 m district, generated from the 01-city placement and road plan.

The three building functions are reusable shells with walkable floor plates,
entrances and fixed interior zones. The 64 primary sites come from the
numerical blueprint; compact infill buildings occupy checked gaps between them.
"""

from __future__ import annotations

import json
import math
import random
from dataclasses import replace
from pathlib import Path

from promodeler.core import (
    Array, Asset, AssetGenerator, Box, Camera, Cone, Cylinder, Extrude, GenerationInput,
    Material, ModelingError, Part, Profile, RenderSettings, Sphere, Transform, srgb,
)


DESIGNS = Path(__file__).resolve().parent.parent / "blueprints" / "japan-realistic-v1"
CITY = json.loads((DESIGNS / "01-city" / "blueprint.json").read_text(encoding="utf-8"))
BUILDINGS = {
    name: json.loads((DESIGNS / name / "blueprint.json").read_text(encoding="utf-8"))
    for name in ("02-apartment", "03-convenience", "04-office")
}
ROAD_CENTERS = (-125.0, 0.0, 125.0)


def _overlap(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> bool:
    return a[0] < b[2] and a[2] > b[0] and a[1] < b[3] and a[3] > b[1]


def footprint(placement: dict) -> tuple[float, float, float, float]:
    size_x, _, size_z = BUILDINGS[placement["blueprint"]]["dimensions"]["envelope_xyz_m"]
    yaw = placement["yaw_rad"]
    half_x = (abs(math.cos(yaw)) * size_x + abs(math.sin(yaw)) * size_z) / 2
    half_z = (abs(math.sin(yaw)) * size_x + abs(math.cos(yaw)) * size_z) / 2
    x, _, z = placement["position_m"]
    return (x - half_x, z - half_z, x + half_x, z + half_z)


def validate_city_layout(design: dict = CITY) -> None:
    """Catch missing sites, road encroachment and footprint collisions before Blender."""
    placements = design["placements"]
    if len(placements) != 64 or len({item["id"] for item in placements}) != 64:
        raise ModelingError("city.placements", "The city needs 64 uniquely named building placements.")
    roads = [tuple(zone["rect_xz_m"]) for zone in design["layout"]]
    footprints = []
    for item in placements:
        if item["blueprint"] not in BUILDINGS:
            raise ModelingError("city.building", f"Unknown building design {item['blueprint']!r}.")
        bounds = footprint(item)
        if min(bounds[0], bounds[1]) < -250 or max(bounds[2], bounds[3]) > 250:
            raise ModelingError("city.boundary", f"{item['id']} extends beyond the 500 m boundary.")
        if any(_overlap(bounds, road) for road in roads):
            raise ModelingError("city.roadCollision", f"{item['id']} overlaps a designed road.")
        if any(_overlap(bounds, other) for other in footprints):
            raise ModelingError("city.buildingCollision", f"{item['id']} overlaps another building.")
        footprints.append(bounds)


def _position(x: float, y: float, z: float, origin: tuple[float, float, float], yaw: float):
    ox, oy, oz = origin
    return (ox + x * math.cos(yaw) + z * math.sin(yaw), oy + y,
            oz - x * math.sin(yaw) + z * math.cos(yaw))


def box(parts: list[Part], name: str, bounds: tuple[float, float, float, float, float, float],
        material: str, *, origin=(0.0, 0.0, 0.0), yaw: float = 0.0,
        repeat: tuple | None = None) -> None:
    x0, x1, y0, y1, z0, z1 = bounds
    center = _position((x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2, origin, yaw)
    repeats = (repeat,) if repeat and isinstance(repeat[0], int) else (repeat or ())
    modifiers = tuple(Array(count=count, offset=offset) for count, offset in repeats)
    parts.append(Part(id=name, shape=Box(size=(x1 - x0, y1 - y0, z1 - z0)),
                      material=material, transform=Transform(translation=center, rotation=(0.0, yaw, 0.0)),
                      modifiers=modifiers))


def cylinder(parts: list[Part], name: str, x: float, y: float, z: float, radius: float,
             height: float, material: str, *, origin=(0.0, 0.0, 0.0), segments=12) -> None:
    parts.append(Part(id=name, shape=Cylinder(radius=radius, height=height, segments=segments),
                      material=material, transform=Transform(translation=_position(x, y, z, origin, 0.0))))


def primitive(parts: list[Part], name: str, shape, material: str,
              center: tuple[float, float, float], *, origin=(0.0, 0.0, 0.0),
              yaw: float = 0.0, repeat: tuple | None = None) -> None:
    repeats = (repeat,) if repeat and isinstance(repeat[0], int) else (repeat or ())
    parts.append(Part(id=name, shape=shape, material=material,
                      transform=Transform(translation=_position(*center, origin, yaw),
                                          rotation=(0.0, yaw, 0.0)),
                      modifiers=tuple(Array(count=count, offset=offset)
                                      for count, offset in repeats)))


def _street_segments() -> tuple[tuple[float, float], ...]:
    return ((-250.0, -130.0), (-120.0, -10.0), (10.0, 120.0), (130.0, 250.0))


def roads(parts: list[Part]) -> None:
    box(parts, "ground", (-250, 250, -0.3, 0, -250, 250), "asphalt")
    for index, (x0, x1) in enumerate(_street_segments()):
        for j, (z0, z1) in enumerate(_street_segments()):
            box(parts, f"block_{index}_{j}", (x0, x1, 0, 0.035, z0, z1), "site_paving")
    for road_index, center in enumerate(ROAD_CENTERS):
        half = 10.0 if center == 0 else 5.0
        carriage = 6.0 if center == 0 else 3.0
        walk_material = "brick_walk" if center == 0 else "asphalt_walk"
        for segment, (start, end) in enumerate(_street_segments()):
            for side in (-1, 1):
                z0, z1 = (center - half, center - carriage) if side < 0 else (center + carriage, center + half)
                x0, x1 = (center - half, center - carriage) if side < 0 else (center + carriage, center + half)
                box(parts, f"walk_ew_{road_index}_{segment}_{side}",
                    (start, end, 0, 0.15, z0, z1), walk_material)
                box(parts, f"walk_ns_{road_index}_{segment}_{side}",
                    (x0, x1, 0, 0.15, start, end), walk_material)
                curb_z = center + side * (carriage + 0.09)
                curb_x = center + side * (carriage + 0.09)
                box(parts, f"curb_ew_{road_index}_{segment}_{side}",
                    (start, end, 0, 0.15, curb_z - 0.09, curb_z + 0.09), "concrete")
                box(parts, f"curb_ns_{road_index}_{segment}_{side}",
                    (curb_x - 0.09, curb_x + 0.09, 0, 0.15, start, end), "concrete")
            # Keep marking arrays away from crossings and never run through a junction.
            count = max(1, int((end - start - 6) // 6))
            box(parts, f"lane_ew_{road_index}_{segment}",
                (start + 3, start + 6, 0.002, 0.0035, center - 0.075, center + 0.075),
                "marking", repeat=(count, (6, 0, 0)))
            box(parts, f"lane_ns_{road_index}_{segment}",
                (center - 0.075, center + 0.075, 0.002, 0.0035, start + 3, start + 6),
                "marking", repeat=(count, (0, 0, 6)))
        for other_index, crossing in enumerate(ROAD_CENTERS):
            other_half = 10.0 if crossing == 0 else 5.0
            for side in (-1, 1):
                x = crossing + side * (other_half + 2.5)
                z = center + side * (half + 2.5)
                box(parts, f"cross_ew_{road_index}_{other_index}_{side}",
                    (x - 1.8, x - 1.35, 0.002, 0.0035, center - carriage, center + carriage),
                    "marking", repeat=(5, (0.9, 0, 0)))
                box(parts, f"cross_ns_{road_index}_{other_index}_{side}",
                    (crossing - (6 if crossing == 0 else 3), crossing + (6 if crossing == 0 else 3),
                     0.002, 0.0035, z - 1.8, z - 1.35),
                    "marking", repeat=(5, (0, 0, 0.9)))
    # The blueprint's curb is a standard 1 m section, rather than an origin-placed site object.
    box(parts, "curb_standard", (-15.5, -14.5, 0, 0.15, 6, 6.18), "concrete")


def apartment(parts: list[Part], placement: dict) -> None:
    prefix = f"site_{placement['id']}"
    origin = tuple(placement["position_m"])
    yaw = placement["yaw_rad"]

    def b(name, bounds, material="tile", repeat=None):
        box(parts, f"{prefix}_{name}", bounds, material, origin=origin, yaw=yaw, repeat=repeat)

    b("foundation", (-12, 12, -0.18, 0, -7, 7), "concrete")
    floors = (6, (0, 3, 0))
    bays = (4, (6, 0, 0))
    both = (bays, floors)
    b("slabs", (-12, 12, 0, 0.2, -7, 7), "concrete", floors)
    b("corridors", (-12, 12, 0, 0.2, -8.8, -7), "concrete", floors)
    b("balconies", (-12, 12, 0, 0.2, 7, 8.5), "concrete", floors)
    b("balcony_glass", (-11.9, 11.9, 0.2, 1.1, 8.44, 8.45), "glass", floors)
    b("balcony_rails", (-12, 12, 1.08, 1.12, 8.42, 8.5), "metal", floors)
    for side, x0, x1 in (("w", -12, -11.8), ("e", 11.8, 12)):
        b(f"balcony_end_{side}", (x0, x1, 0.2, 3, 7, 8.5), "tile", floors)
    for index, x in enumerate((-6.0, 0.0, 6.0)):
        b(f"balcony_divider_{index}", (x - 0.08, x + 0.08, 0.2, 3, 7, 8.5),
          "tile", floors)
    b("side_w", (-12, -11.8, 0.2, 3, -7, 7), repeat=floors)
    b("side_e", (11.8, 12, 0.2, 3, -7, 7), repeat=floors)
    b("north_headers", (-12, 12, 2.45, 3, -7, -6.8), repeat=floors)
    b("south_headers", (-12, 12, 2.55, 3, 6.8, 7), repeat=floors)
    b("spandrels", (-12, 12, 0.2, 0.75, 6.8, 7), repeat=floors)
    b("windows", (-11.5, -6.5, 0.75, 2.55, 6.96, 6.97), "glass", both)
    b("window_frames", (-9.02, -8.98, 0.75, 2.55, 6.97, 7.02), "metal", both)
    b("unit_doors", (-9.6, -8.4, 0.2, 2.4, -7.03, -6.98), "paint", both)
    b("north_piers_l", (-12, -9.65, 0.2, 2.45, -7, -6.8), repeat=both)
    b("north_piers_r", (-8.35, -6, 0.2, 2.45, -7, -6.8), repeat=both)
    b("party_wall_w", (-6.06, -5.94, 0.2, 2.85, -6.8, 6.8), "paint", floors)
    b("party_wall_e", (5.94, 6.06, 0.2, 2.85, -6.8, 6.8), "paint", floors)
    b("party_wall_center_upper", (-0.06, 0.06, 3.2, 5.85, -6.8, 6.8), "paint",
      (5, (0, 3, 0)))
    upper = (5, (0, 3, 0))
    b("bath_walls_upper", (-11.7, -9.6, 3.2, 5.4, -4.4, -4.28), "paint", (bays, upper))
    b("kitchens_upper", (-7.2, -6.35, 3.2, 4.08, -4.0, -1.2), "paint", (bays, upper))
    for bay in (0, 3):
        x = -12 + bay * 6
        b(f"bath_wall_ground_{bay}", (x + 0.3, x + 2.4, 0.2, 2.4, -4.4, -4.28), "paint")
        b(f"kitchen_ground_{bay}", (x + 4.8, x + 5.65, 0.2, 1.08, -4, -1.2), "paint")
    b("roof", (-12, 12, 17.8, 18, -7, 7), "slate")
    for side, x0, x1 in (("w", -12, -11.8), ("e", 11.8, 12)):
        b(f"parapet_{side}", (x0, x1, 18, 19.1, -7, 7), "tile")
    b("parapet_n", (-12, 12, 18, 19.1, -7, -6.8), "tile")
    b("parapet_s", (-12, 12, 18, 19.1, 6.8, 7), "tile")
    # Two 9-tread runs reverse at a 1.2 m landing. The rear entrance remains
    # open to the access corridor at every level.
    for side, left in (("w", -15.0), ("e", 12.0)):
        def waist(name: str, x: float, profile: tuple[tuple[float, float], ...]) -> None:
            parts.append(Part(
                id=f"{prefix}_stair_{side}_{name}",
                shape=Extrude(profile=Profile(profile), depth=0.1, axis="x"),
                material="concrete",
                transform=Transform(translation=_position(x, 0, 0, origin, yaw),
                                    rotation=(0, yaw, 0)),
                modifiers=(Array(count=5, offset=(0, 3, 0)),),
            ))

        b(f"stair_{side}_corridor_bridge", (left, left + 3, 0, 0.2, -8.8, -7),
          "concrete", floors)
        b(f"stair_{side}_bridge_glass", (left + 0.1, left + 2.9, 0.2, 1.1,
                                        -8.8, -8.79), "glass", floors)
        b(f"stair_{side}_bridge_rail", (left, left + 3, 1.08, 1.12,
                                       -8.8, -8.74), "metal", floors)
        b(f"stair_{side}_outside", (left, left + 0.2, 0, 18, -7, 1), "tile")
        b(f"stair_{side}_inside", (left + 2.8, left + 3, 0, 18, -7, 1), "tile")
        b(f"stair_{side}_back", (left + 0.2, left + 2.8, 2.35, 3, -7, -6.8),
          "tile", floors)
        b(f"stair_{side}_back_pier_w", (left, left + 0.2, 0, 18, -7, -6.8), "tile")
        b(f"stair_{side}_back_pier_e", (left + 2.8, left + 3, 0, 18, -7, -6.8), "tile")
        b(f"stair_{side}_landings", (left, left + 3, 0, 0.2, -7, -5.4), "concrete", floors)
        b(f"stair_{side}_mid_landings", (left + 0.2, left + 2.8, 1.5, 1.7,
                                         -2.88, -1.68), "concrete", (5, (0, 3, 0)))
        b(f"stair_{side}_flight_a", (left + 0.3, left + 1.5, 0.206667, 0.366667, -5.4, -5.12),
          "concrete", ((9, (0, 0.166667, 0.28)), (5, (0, 3, 0))))
        b(f"stair_{side}_flight_b", (left + 1.5, left + 2.7, 1.706667, 1.866667, -3.16, -2.88),
          "concrete", ((9, (0, 0.166667, -0.28)), (5, (0, 3, 0))))
        for edge, x in (("outer", left + 0.3), ("inner", left + 1.4)):
            waist("waist_a_" + edge, x,
                  ((5.4, 0.02), (2.88, 1.38), (2.88, 1.54), (5.4, 0.18)))
        for edge, x in (("inner", left + 1.5), ("outer", left + 2.6)):
            waist("waist_b_" + edge, x,
                  ((2.88, 1.52), (5.4, 3.02), (5.4, 3.18), (2.88, 1.68)))
    b("lobby_glass", (-2.9, 2.9, 0.2, 2.5, 6.96, 6.97), "glass")
    b("parking", (-10, 10, 0.035, 0.045, -20, -11), "asphalt")
    b("parking_stripes", (-8.0, -7.85, 0.046, 0.0475, -19, -12), "marking",
      (7, (2.6, 0, 0)))


def convenience(parts: list[Part], placement: dict) -> None:
    prefix = f"site_{placement['id']}"
    origin = tuple(placement["position_m"])
    yaw = placement["yaw_rad"]

    def b(name, bounds, material="paint", repeat=None):
        box(parts, f"{prefix}_{name}", bounds, material, origin=origin, yaw=yaw, repeat=repeat)

    b("foundation", (-9, 9, -0.15, 0, -6, 6), "concrete")
    b("sales_floor", (-8.85, 8.85, 0, 0.06, -5.85, 5.85), "floor_tile_300")
    b("roof", (-9, 9, 4.02, 4.2, -6, 6), "slate")
    b("wall_n", (-9, 9, 0, 4.02, -6, -5.85), "store_tile")
    b("wall_w", (-9, -8.85, 0, 4.02, -6, 6), "store_tile")
    b("wall_e", (8.85, 9, 0, 4.02, -6, 6), "store_tile")
    b("south_sill", (-9, 9, 0, 0.15, 5.85, 6), "store_tile")
    b("front_glass_left", (-8.85, -1.85, 0.15, 2.8, 5.97, 5.98), "glass")
    b("front_glass_right", (1.85, 8.85, 0.15, 2.8, 5.97, 5.98), "glass")
    b("front_mullions_left", (-8.27, -8.23, 0.15, 2.8, 5.95, 6), "metal",
      repeat=(5, (1.5, 0, 0)))
    b("front_mullions_right", (2.23, 2.27, 0.15, 2.8, 5.95, 6), "metal",
      repeat=(5, (1.5, 0, 0)))
    # The paired automatic leaves rest half open and slide behind fixed sidelights.
    b("entry_sidelight_left", (-1.85, -0.9, 0.15, 2.35, 5.975, 5.985), "glass")
    b("entry_sidelight_right", (0.9, 1.85, 0.15, 2.35, 5.975, 5.985), "glass")
    b("entry_left", (-1.35, -0.45, 0.15, 2.35, 5.94, 5.95), "glass")
    b("entry_right", (0.45, 1.35, 0.15, 2.35, 5.94, 5.95), "glass")
    b("entry_left_rail_w", (-1.35, -1.325, 0.15, 2.35, 5.925, 5.965), "metal")
    b("entry_left_rail_e", (-0.475, -0.45, 0.15, 2.35, 5.925, 5.965), "metal")
    b("entry_right_rail_w", (0.45, 0.475, 0.15, 2.35, 5.925, 5.965), "metal")
    b("entry_right_rail_e", (1.325, 1.35, 0.15, 2.35, 5.925, 5.965), "metal")
    b("entry_left_top", (-1.35, -0.45, 2.30, 2.35, 5.925, 5.965), "metal")
    b("entry_right_top", (0.45, 1.35, 2.30, 2.35, 5.925, 5.965), "metal")
    b("entry_track", (-1.85, 1.85, 2.35, 2.45, 5.90, 6.0), "metal")
    b("entry_transom", (-1.85, 1.85, 2.45, 2.8, 5.97, 5.98), "glass")
    b("entry_sensor", (-0.22, 0.22, 2.46, 2.55, 5.94, 5.99), "device_dark")
    b("entry_threshold", (-0.9, 0.9, 0.06, 0.08, 5.80, 6.0), "metal")
    b("entry_frame_w", (-1.87, -1.83, 0.15, 2.8, 5.94, 6.0), "metal")
    b("entry_frame_e", (1.83, 1.87, 0.15, 2.8, 5.94, 6.0), "metal")
    b("sign_band", (-9, 9, 3.05, 3.7, 5.96, 6), "teal")
    b("roof_fascia", (-9, 9, 3.7, 4.2, 5.86, 6), "store_tile")
    b("backroom_wall_l", (-8.85, 5.8, 0.06, 2.8, -2.9, -2.8), "paint")
    b("backroom_wall_r", (5.9, 8.85, 0.06, 2.8, -2.9, -2.8), "paint")
    b("toilet_wall", (5.8, 5.9, 0.06, 2.8, -5.85, -2.9), "paint")
    b("checkout", (-7.6, -6.85, 0, 0.9, 0.8, 4.85), "paint")
    b("checkout_return", (-7.6, -4.0, 0, 0.9, 4.1, 4.85), "paint")
    b("checkout_top", (-7.63, -6.82, 0.88, 0.92, 0.77, 4.88), "slate")
    b("checkout_return_top", (-7.63, -3.97, 0.88, 0.92, 4.07, 4.88), "slate")
    # Rear display has no glass or door; the separate right-wall cooler is enclosed.
    b("cold_wall", (-5.4, 5.4, 0, 2.1, -2.8, -2.7), "metal")
    b("cold_wall_base", (-5.4, 5.4, 0, 0.16, -2.8, -2.0), "metal")
    b("cold_wall_top", (-5.4, 5.4, 1.98, 2.1, -2.8, -2.0), "metal")
    b("cold_wall_side_w", (-5.4, -5.3, 0, 2.1, -2.8, -2.0), "metal")
    b("cold_wall_side_e", (5.3, 5.4, 0, 2.1, -2.8, -2.0), "metal")
    b("cold_shelves", (-5.28, 5.28, 0.37, 0.4, -2.69, -2.06), "paint",
      repeat=(4, (0, 0.45, 0)))
    b("cold_shelf_lips", (-5.28, 5.28, 0.37, 0.43, -2.04, -2.0), "metal",
      repeat=(4, (0, 0.45, 0)))
    b("right_cooler_base", (7.8, 8.8, 0, 0.16, -1.35, 2.75), "metal")
    b("right_cooler_top", (7.8, 8.8, 2.13, 2.25, -1.35, 2.75), "metal")
    b("right_cooler_back", (8.73, 8.8, 0, 2.25, -1.35, 2.75), "metal")
    b("right_cooler_end_n", (7.8, 8.8, 0, 2.25, -1.35, -1.27), "metal")
    b("right_cooler_end_s", (7.8, 8.8, 0, 2.25, 2.67, 2.75), "metal")
    b("right_cooler_shelves", (7.88, 8.72, 0.42, 0.45, -1.25, 2.65), "paint",
      repeat=(4, (0, 0.45, 0)))
    for door, z0 in enumerate((-1.35, 0.02, 1.39)):
        b(f"right_cooler_door_{door}", (7.79, 7.8, 0.18, 2.10, z0, z0 + 1.35), "glass")
        b(f"right_cooler_handle_{door}", (7.75, 7.79, 0.9, 1.35,
                                            z0 + 1.16, z0 + 1.20), "metal")
    b("right_cooler_frames", (7.76, 7.81, 0.16, 2.13, -1.35, -1.31), "metal",
      repeat=(4, (0, 0, 1.365)))
    for shelf, x in enumerate((-3.0, 0.0, 3.0)):
        b(f"shelf_{shelf}_boards", (x - 0.45, x + 0.45, 0.15, 0.175, -0.75, 2.85),
          "paint", repeat=(5, (0, 0.3, 0)))
        b(f"shelf_{shelf}_left", (x - 0.45, x - 0.425, 0, 1.5, -0.75, -0.70), "metal")
        b(f"shelf_{shelf}_right", (x + 0.425, x + 0.45, 0, 1.5, -0.75, -0.70), "metal")
        b(f"shelf_{shelf}_left_rear", (x - 0.45, x - 0.425, 0, 1.5, 2.80, 2.85), "metal")
        b(f"shelf_{shelf}_right_rear", (x + 0.425, x + 0.45, 0, 1.5, 2.80, 2.85), "metal")
        b(f"shelf_{shelf}_front", (x - 0.45, x + 0.45, 0, 0.18, 2.825, 2.85), "paint")
    # Every shelf board is filled end-to-end while the 2.1 m aisles stay open.
    cup = Cone(radius=0.07, top_radius=0.085, height=0.16, segments=10)
    for level in range(5):
        y = 0.255 + level * 0.3
        for row, x in enumerate((-3.22, -2.78)):
            for tone, material in enumerate(("pack_red", "pack_yellow")):
                primitive(parts, f"{prefix}_cup_noodles_{level}_{row}_{tone}", cup,
                          material, (x, y, -0.665 + tone * 0.18),
                          origin=origin, yaw=yaw, repeat=(10, (0, 0, 0.36)))
        for row, x in enumerate((-0.24, 0.24)):
            primitive(parts, f"{prefix}_bread_{level}_{row}",
                      Sphere(radius=0.1, segments=8, rings=5), "bread",
                      (x, 0.275 + level * 0.3, -0.65), origin=origin, yaw=yaw,
                      repeat=(18, (0, 0, 0.2)))
        for row, x0 in enumerate((2.58, 2.89, 3.2)):
            b(f"daily_goods_{level}_{row}",
              (x0, x0 + 0.22, 0.175 + level * 0.3, 0.365 + level * 0.3,
               -0.74, -0.572),
              ("pack_blue", "pack_green", "pack_yellow", "pack_red", "pack_blue")[level],
              repeat=(21, (0, 0, 0.17)))
    # Produce and desserts remain fully accessible on the doorless rear display.
    for level in range(4):
        y = 0.50 + level * 0.45
        for row, z in enumerate((-2.48, -2.24)):
            primitive(parts, f"{prefix}_fresh_{level}_{row}",
                      Sphere(radius=0.10, segments=8, rings=5),
                      "produce_green" if (level + row) % 2 else "produce_red",
                      (-5.0, y, z), origin=origin, yaw=yaw,
                      repeat=(16, (0.24, 0, 0)))
            primitive(parts, f"{prefix}_dessert_{level}_{row}",
                      Cone(radius=0.08, top_radius=0.10, height=0.16, segments=10),
                      "dessert_cream" if (level + row) % 2 else "dessert_pink",
                      (0.45, y, z), origin=origin, yaw=yaw,
                      repeat=(18, (0.25, 0, 0)))
        for row, x in enumerate((8.10, 8.48)):
            b(f"right_cooler_goods_{level}_{row}",
              (x - 0.11, x + 0.11, 0.45 + level * 0.45, 0.70 + level * 0.45,
               -1.18, -0.94),
              ("pack_green", "pack_blue", "dessert_pink", "pack_yellow")[level],
              repeat=(11, (0, 0, 0.35)))
    # Three tiers of magazines face the south glazing, with a copier beside them.
    b("magazine_base", (1.4, 4.5, 0, 0.16, 4.45, 5.42), "device_white")
    for tier in range(3):
        shelf_y = 0.47 + tier * 0.43
        b(f"magazine_shelf_{tier}", (1.4, 4.5, shelf_y - 0.035, shelf_y,
                                     4.48, 5.42), "metal")
        for tone, material in enumerate(("pack_blue", "pack_red")):
            b(f"magazine_covers_{tier}_{tone}",
              (1.46 + tone * 0.25, 1.67 + tone * 0.25,
               shelf_y, shelf_y + 0.33, 5.30, 5.33), material,
              repeat=(6, (0.5, 0, 0)))
    b("printer_cabinet", (6.2, 7.7, 0, 0.86, 4.22, 5.52), "device_white")
    b("printer_body", (6.28, 7.62, 0.86, 1.28, 4.25, 5.45), "device_white")
    b("printer_scanner", (6.25, 7.65, 1.28, 1.38, 4.2, 5.48), "device_dark")
    b("printer_screen", (6.82, 7.22, 1.01, 1.19, 5.449, 5.456), "screen")
    b("printer_paper_slot", (6.46, 7.48, 0.66, 0.70, 5.517, 5.528), "device_dark")
    # Register and payment equipment belong on the entrance-left checkout.
    b("register_drawer", (-7.53, -6.94, 0.92, 1.04, 2.15, 3.05), "device_dark")
    b("register_screen", (-7.40, -7.02, 1.04, 1.42, 2.78, 2.85), "screen")
    b("register_payment", (-5.44, -5.16, 0.92, 1.13, 4.33, 4.63), "device_dark")
    b("register_receipt", (-4.94, -4.64, 0.92, 1.08, 4.22, 4.55), "device_white")
    b("lot", (-9, 9, 0.035, 0.045, 9, 19), "asphalt")
    b("lot_stripes", (-7.5, -7.35, 0.046, 0.0475, 10.0, 18.5), "marking",
      repeat=(6, (3, 0, 0)))


def office(parts: list[Part], placement: dict) -> None:
    prefix = f"site_{placement['id']}"
    origin = tuple(placement["position_m"])
    yaw = placement["yaw_rad"]

    def b(name, bounds, material="concrete", repeat=None):
        box(parts, f"{prefix}_{name}", bounds, material, origin=origin, yaw=yaw, repeat=repeat)

    b("foundation", (-12, 12, -0.25, 0, -9, 9))
    def level(tag: str, y: float, ceiling: float, repeat=None):
        b(f"floor_{tag}", (-12, 12, y, y + 0.25, -9, 9),
          "stone" if tag == "ground" else "carpet", repeat)
        b(f"south_glass_{tag}", (-11.8, 11.8, y + 0.25, ceiling - 0.25, 8.96, 8.97), "glass", repeat)
        b(f"north_glass_{tag}", (-11.8, 11.8, y + 0.25, ceiling - 0.25, -8.97, -8.96), "glass", repeat)
        b(f"west_glass_{tag}", (-11.97, -11.96, y + 0.25, ceiling - 0.25, -8.8, 8.8), "glass", repeat)
        b(f"east_glass_{tag}", (11.96, 11.97, y + 0.25, ceiling - 0.25, -8.8, 8.8), "glass", repeat)
        x_mullions = (16, (1.5, 0, 0))
        z_mullions = (12, (0, 0, 1.5))
        b(f"south_mullions_{tag}", (-11.28, -11.22, y + 0.25, ceiling - 0.25, 8.92, 9),
          "metal", (x_mullions, repeat) if repeat else x_mullions)
        b(f"north_mullions_{tag}", (-11.28, -11.22, y + 0.25, ceiling - 0.25, -9, -8.92),
          "metal", (x_mullions, repeat) if repeat else x_mullions)
        b(f"west_mullions_{tag}", (-12, -11.92, y + 0.25, ceiling - 0.25, -8.27, -8.21),
          "metal", (z_mullions, repeat) if repeat else z_mullions)
        b(f"east_mullions_{tag}", (11.92, 12, y + 0.25, ceiling - 0.25, -8.27, -8.21),
          "metal", (z_mullions, repeat) if repeat else z_mullions)
        b(f"spandrel_{tag}", (-12, 12, y, y + 0.36, 8.98, 9), "slate", repeat)
        b(f"service_wall_{tag}", (-7.8, 7.8, y + 0.25, ceiling - 0.3, -3.05, -3), "paint", repeat)
        b(f"west_stair_wall_{tag}", (-8, -7.8, y + 0.25, ceiling - 0.3, -8.8, -3), "paint", repeat)
        b(f"east_stair_wall_{tag}", (7.8, 8, y + 0.25, ceiling - 0.3, -8.8, -3), "paint", repeat)
        b(f"lift_bank_{tag}", (-2.5, 2.5, y + 0.25, ceiling - 0.3, -8.8, -5.8), "metal", repeat)
        b(f"toilet_core_{tag}", (-7.7, -2.8, y + 0.25, ceiling - 0.3, -8.8, -5.8), "paint", repeat)
        b(f"service_core_{tag}", (2.8, 7.7, y + 0.25, ceiling - 0.3, -8.8, -5.8), "paint", repeat)

    level("ground", 0.0, 4.2)
    level("upper", 4.2, 7.8, (7, (0, 3.6, 0)))
    for side, left in (("w", -11.6), ("e", 8.2)):
        b(f"stair_{side}_ground_a", (left, left + 1.2, 0.015, 0.175, -8.5, -8.22),
          "concrete", (12, (0, 0.175, 0.28)))
        b(f"stair_{side}_ground_b", (left + 1.2, left + 2.4, 2.115, 2.275, -5.42, -5.14),
          "concrete", (12, (0, 0.175, -0.28)))
        b(f"stair_{side}_upper_a", (left, left + 1.2, 4.22, 4.38, -8.5, -8.22),
          "concrete", ((10, (0, 0.18, 0.28)), (7, (0, 3.6, 0))))
        b(f"stair_{side}_upper_b", (left + 1.2, left + 2.4, 6.02, 6.18, -5.98, -5.7),
          "concrete", ((10, (0, 0.18, -0.28)), (7, (0, 3.6, 0))))
    b("roof", (-12, 12, 29.15, 29.4, -9, 9))
    b("roof_screen", (-4, 4, 29.4, 30.6, -3, 3), "metal")
    b("lobby_entry", (-1.2, 1.2, 0, 3.2, 8.97, 8.99), "glass")
    b("plaza", (-11, 11, 0.035, 0.055, 10, 18), "stone")
    b("loading", (-10, 10, 0.035, 0.045, -20, -11), "asphalt")


def site_furnishings(parts: list[Part], placements: list[dict],
                    infill_bounds: list[tuple[float, float, float, float]] | None = None) -> None:
    # Two planted trees per lot. Offsets stay inside each 50 m site and outside roofs.
    for placement in placements:
        x, _, z = placement["position_m"]
        extent_x, _, extent_z = BUILDINGS[placement["blueprint"]]["dimensions"]["envelope_xyz_m"]
        for side in (-1, 1):
            tx = x + side * (extent_x / 2 + 4.0)
            tz = z + (-12.0 if placement["blueprint"] == "03-convenience" else 12.0)
            if any(left - 2.5 < tx < right + 2.5 and back - 2.5 < tz < front + 2.5
                   for left, back, right, front in (infill_bounds or ())):
                continue
            tag = f"tree_{placement['id']}_{side}"
            cylinder(parts, f"{tag}_trunk", tx, 1.6, tz, 0.18, 3.2, "bark", segments=10)
            parts.append(Part(id=f"{tag}_crown", shape=Sphere(radius=2.2, segments=10, rings=6),
                              material="foliage", transform=Transform(translation=(tx, 4.0, tz),
                                                                        scale=(1.0, 0.8, 1.0))))
    # Local roads use 25 m streetlight and 35 m utility-pole rhythms. Junctions
    # are kept clear for at least 8 m, as specified by the site plan.
    for axis in ("x", "z"):
        for road in (-125.0, 125.0):
            for index in range(20):
                along = -237.5 + 25 * index
                if min(abs(along - crossing) for crossing in ROAD_CENTERS) < 8:
                    continue
                x, z = (road + 4.2, along) if axis == "x" else (along, road + 4.2)
                tag = f"lamp_{axis}_{int(road)}_{index}"
                cylinder(parts, f"{tag}_post", x, 3.5, z, 0.06, 7.0, "metal")
                box(parts, f"{tag}_arm", (x - 0.08, x + 0.08, 6.85, 6.95,
                                           z - 1.0, z + 0.15), "metal")
                box(parts, f"{tag}_head", (x - 0.25, x + 0.25, 6.77, 6.86,
                                            z - 1.25, z - 0.8), "lamp")
            for index in range(14):
                along = -227.5 + 35 * index
                if min(abs(along - crossing) for crossing in ROAD_CENTERS) < 8:
                    continue
                x, z = (road - 4.2, along) if axis == "x" else (along, road - 4.2)
                tag = f"pole_{axis}_{int(road)}_{index}"
                cylinder(parts, tag, x, 4.4, z, 0.11, 8.8, "concrete")


def city_materials() -> tuple[Material, ...]:
    return (
        Material("asphalt", base_color=srgb(0.263, 0.275, 0.278), roughness=0.88),
        Material("concrete", base_color=srgb(0.64, 0.64, 0.62), roughness=0.75),
        Material("tile", base_color=srgb(0.72, 0.71, 0.68), roughness=0.45),
        Material("floor_tile_300", base_color=srgb(0.82, 0.81, 0.77), roughness=0.42),
        Material("metal", base_color=srgb(0.27, 0.286, 0.29), metallic=1, roughness=0.32),
        Material("glass", base_color=srgb(0.68, 0.78, 0.79, 0.54), roughness=0.08, alpha_mode="blend"),
        Material("paint", base_color=srgb(0.898, 0.894, 0.855), roughness=0.55),
        Material("site_paving", base_color=srgb(0.43, 0.45, 0.43), roughness=0.8),
        Material("slate", base_color=srgb(0.22, 0.25, 0.27), roughness=0.48),
        Material("teal", base_color=srgb(0.06, 0.42, 0.44), roughness=0.45),
        Material("stone", base_color=srgb(0.62, 0.62, 0.61), roughness=0.65),
        Material("carpet", base_color=srgb(0.47, 0.5, 0.51), roughness=0.9),
        Material("marking", base_color=srgb(0.88, 0.88, 0.83), roughness=0.8),
        Material("bark", base_color=srgb(0.24, 0.19, 0.13), roughness=0.85),
        Material("foliage", base_color=srgb(0.17, 0.29, 0.17), roughness=0.85),
        Material("lamp", base_color=srgb(0.75, 0.78, 0.75), roughness=0.4),
        Material("brick_walk", base_color=srgb(0.53, 0.31, 0.25), roughness=0.82),
        Material("asphalt_walk", base_color=srgb(0.37, 0.39, 0.39), roughness=0.9),
        Material("brick_red", base_color=srgb(0.56, 0.29, 0.23), roughness=0.79),
        Material("brick_sand", base_color=srgb(0.73, 0.57, 0.42), roughness=0.77),
        Material("brick_charcoal", base_color=srgb(0.32, 0.34, 0.33), roughness=0.82),
        Material("tile_sand", base_color=srgb(0.77, 0.69, 0.56), roughness=0.48),
        Material("tile_rose", base_color=srgb(0.69, 0.54, 0.51), roughness=0.47),
        Material("tile_gray", base_color=srgb(0.58, 0.63, 0.65), roughness=0.48),
        Material("paint_cream", base_color=srgb(0.88, 0.82, 0.68), roughness=0.57),
        Material("paint_sage", base_color=srgb(0.66, 0.75, 0.65), roughness=0.59),
        Material("paint_rose", base_color=srgb(0.81, 0.67, 0.68), roughness=0.57),
        Material("paint_blue", base_color=srgb(0.62, 0.71, 0.78), roughness=0.57),
        Material("concrete_warm", base_color=srgb(0.67, 0.62, 0.54), roughness=0.77),
        Material("concrete_cool", base_color=srgb(0.55, 0.61, 0.66), roughness=0.76),
        Material("slate_blue", base_color=srgb(0.18, 0.28, 0.34), roughness=0.49),
        Material("glass_blue", base_color=srgb(0.55, 0.72, 0.82, 0.54), roughness=0.08, alpha_mode="blend"),
        Material("glass_green", base_color=srgb(0.60, 0.78, 0.69, 0.54), roughness=0.08, alpha_mode="blend"),
        Material("glass_smoke", base_color=srgb(0.58, 0.65, 0.69, 0.54), roughness=0.08, alpha_mode="blend"),
        Material("store_tile", base_color=srgb(0.84, 0.80, 0.70), roughness=0.56),
        Material("store_tile_blue", base_color=srgb(0.66, 0.75, 0.78), roughness=0.56),
        Material("store_tile_rose", base_color=srgb(0.79, 0.67, 0.64), roughness=0.56),
        Material("pack_red", base_color=srgb(0.68, 0.23, 0.18), roughness=0.63),
        Material("pack_yellow", base_color=srgb(0.84, 0.65, 0.28), roughness=0.64),
        Material("pack_green", base_color=srgb(0.28, 0.55, 0.35), roughness=0.65),
        Material("pack_blue", base_color=srgb(0.25, 0.42, 0.62), roughness=0.61),
        Material("bread", base_color=srgb(0.70, 0.46, 0.25), roughness=0.78),
        Material("produce_green", base_color=srgb(0.25, 0.54, 0.24), roughness=0.76),
        Material("produce_red", base_color=srgb(0.66, 0.21, 0.17), roughness=0.66),
        Material("dessert_cream", base_color=srgb(0.91, 0.83, 0.67), roughness=0.57),
        Material("dessert_pink", base_color=srgb(0.82, 0.51, 0.58), roughness=0.57),
        Material("device_white", base_color=srgb(0.77, 0.79, 0.78), roughness=0.39),
        Material("device_dark", base_color=srgb(0.13, 0.16, 0.18), roughness=0.38),
        Material("screen", base_color=srgb(0.06, 0.13, 0.16), roughness=0.16,
                 emission_color=srgb(0.05, 0.20, 0.23), emission_strength=0.35),
    )


def city_tile_specs() -> dict[str, dict]:
    """Repeatable maps with a fixed physical pitch and at least 512 px/m."""
    return {
        "asphalt": {"pattern": "asphalt", "scale_m": 0.4, "resolution": 256,
                    "normal_strength": 0.08},
        "concrete": {"pattern": "concrete", "scale_m": 0.4, "resolution": 256},
        "tile": {"pattern": "ceramic", "scale_m": 0.095, "resolution": 256},
        "floor_tile_300": {"pattern": "floor_tile", "scale_m": 0.3, "resolution": 256},
        "metal": {"pattern": "brushed_metal", "scale_m": 0.3, "resolution": 256},
        "paint": {"pattern": "plaster", "scale_m": 0.4, "resolution": 256},
        "site_paving": {"pattern": "paving", "scale_m": 0.4, "resolution": 256},
        "slate": {"pattern": "stone", "scale_m": 0.4, "resolution": 256},
        "teal": {"pattern": "brushed_metal", "scale_m": 0.3, "resolution": 256},
        "stone": {"pattern": "stone", "scale_m": 0.4, "resolution": 256},
        "carpet": {"pattern": "carpet", "scale_m": 0.3, "resolution": 256},
        "bark": {"pattern": "bark", "scale_m": 0.3, "resolution": 256},
        "foliage": {"pattern": "foliage", "scale_m": 0.3, "resolution": 256},
        "brick_walk": {"pattern": "brick", "scale_m": 0.48, "resolution": 256},
        "asphalt_walk": {"pattern": "asphalt", "scale_m": 0.4, "resolution": 256,
                         "normal_strength": 0.08},
        "brick_red": {"pattern": "brick", "scale_m": 0.48, "resolution": 256},
        "brick_sand": {"pattern": "brick", "scale_m": 0.48, "resolution": 256},
        "brick_charcoal": {"pattern": "brick", "scale_m": 0.48, "resolution": 256},
        "tile_sand": {"pattern": "ceramic", "scale_m": 0.095, "resolution": 256},
        "tile_rose": {"pattern": "ceramic", "scale_m": 0.095, "resolution": 256},
        "tile_gray": {"pattern": "ceramic", "scale_m": 0.095, "resolution": 256},
        "paint_cream": {"pattern": "plaster", "scale_m": 0.4, "resolution": 256},
        "paint_sage": {"pattern": "plaster", "scale_m": 0.4, "resolution": 256},
        "paint_rose": {"pattern": "plaster", "scale_m": 0.4, "resolution": 256},
        "paint_blue": {"pattern": "plaster", "scale_m": 0.4, "resolution": 256},
        "concrete_warm": {"pattern": "concrete", "scale_m": 0.4, "resolution": 256},
        "concrete_cool": {"pattern": "concrete", "scale_m": 0.4, "resolution": 256},
        "slate_blue": {"pattern": "stone", "scale_m": 0.4, "resolution": 256},
        "store_tile": {"pattern": "store_tile", "scale_m": 0.3, "resolution": 256},
        "store_tile_blue": {"pattern": "store_tile", "scale_m": 0.3, "resolution": 256},
        "store_tile_rose": {"pattern": "store_tile", "scale_m": 0.3, "resolution": 256},
    }


def _variation(index: int) -> tuple[float, float]:
    rng = random.Random(4103 + index * 97)
    return rng.uniform(0.86, 1.12), rng.uniform(0.86, 1.15)


def _vary_designed_building(parts: list[Part], start: int, placement: dict,
                            index: int) -> None:
    """Vary each blueprint shell around its site centre without shifting the roads."""
    horizontal, vertical = _variation(index)
    rng = random.Random(8521 + index * 113)
    kind = placement["blueprint"]
    if kind == "02-apartment":
        palette = {"tile": rng.choice(("tile", "tile_sand", "tile_rose", "tile_gray")),
                   "paint": rng.choice(("paint", "paint_cream", "paint_sage", "paint_rose"))}
    elif kind == "03-convenience":
        palette = {"paint": rng.choice(("paint", "paint_cream", "paint_sage", "paint_blue")),
                   "tile": rng.choice(("tile", "tile_sand", "tile_gray")),
                   "store_tile": rng.choice(("store_tile", "store_tile_blue",
                                                "store_tile_rose"))}
    else:
        palette = {"concrete": rng.choice(("concrete", "concrete_warm", "concrete_cool")),
                   "slate": rng.choice(("slate", "slate_blue")),
                   "glass": rng.choice(("glass", "glass_blue", "glass_green", "glass_smoke"))}
    ox, oy, oz = placement["position_m"]
    for part_index in range(start, len(parts)):
        part = parts[part_index]
        if part.id.endswith(("_parking", "_parking_stripes", "_lot", "_lot_stripes", "_loading")):
            continue
        transform = part.transform
        x, y, z = transform.translation
        parts[part_index] = replace(
            part, material=palette.get(part.material, part.material),
            transform=replace(transform,
                              translation=(ox + (x - ox) * horizontal,
                                           oy + (y - oy) * vertical,
                                           oz + (z - oz) * horizontal),
                              scale=tuple(value * factor for value, factor in
                                          zip(transform.scale, (horizontal, vertical, horizontal)))))


def infill_sites(placements: list[dict] | None = None) -> list[dict]:
    """Place five compact, varied shells in the gaps of each designed block."""
    placements = CITY["placements"] if placements is None else placements
    xs = sorted({float(p["position_m"][0]) for p in placements})
    zs = sorted({float(p["position_m"][2]) for p in placements})
    if len(xs) != 8 or len(zs) != 8:
        raise ModelingError("city.infillGrid", "Expected an 8 by 8 placement grid.")
    occupied = []
    for index, placement in enumerate(placements):
        horizontal, _ = _variation(index)
        x, _, z = placement["position_m"]
        left, back, right, front = footprint(placement)
        occupied.append((x + (left - x) * horizontal, z + (back - z) * horizontal,
                         x + (right - x) * horizontal, z + (front - z) * horizontal))
    roads = [tuple(zone["rect_xz_m"]) for zone in CITY["layout"]]
    rng = random.Random(91107)
    sites = []
    for row in range(4):
        z0, z1 = zs[2 * row:2 * row + 2]
        zm = (z0 + z1) / 2
        for column in range(4):
            x0, x1 = xs[2 * column:2 * column + 2]
            xm = (x0 + x1) / 2
            for slot, (x, z) in enumerate(((xm, z0), (xm, z1), (x0, zm),
                                           (x1, zm), (xm, zm))):
                width = round(rng.uniform(9.0, 13.0), 2)
                depth = round(rng.uniform(9.0, 13.0), 2)
                bounds = (x - width / 2, z - depth / 2, x + width / 2, z + depth / 2)
                clearance = (bounds[0] - 1.0, bounds[1] - 1.0,
                             bounds[2] + 1.0, bounds[3] + 1.0)
                if any(_overlap(clearance, other) for other in (*occupied, *roads)):
                    continue
                floors = rng.randint(2, 10)
                sites.append({"id": f"infill_{column}_{row}_{slot}", "x": x, "z": z,
                              "width": width, "depth": depth, "floors": floors,
                              "facade": rng.choice(("brick_red", "brick_sand", "brick_charcoal",
                                                    "tile_sand", "tile_rose", "tile_gray",
                                                    "paint_cream", "paint_sage", "paint_blue")),
                              "glass": rng.choice(("glass", "glass_blue", "glass_green")),
                              "bounds": bounds})
                occupied.append(bounds)
    return sites


def _infill_building(parts: list[Part], site: dict) -> None:
    x, z = site["x"], site["z"]
    w, d = site["width"], site["depth"]
    x0, x1, z0, z1 = x - w / 2, x + w / 2, z - d / 2, z + d / 2
    floors = site["floors"]
    height = floors * 3.2
    tag = site["id"] + "_"
    facade = site["facade"]
    box(parts, tag + "foundation", (x0, x1, -0.18, 0.04, z0, z1), "concrete")
    box(parts, tag + "slabs", (x0, x1, 0.04, 0.22, z0, z1), "concrete",
        repeat=(floors, (0, 3.2, 0)))
    box(parts, tag + "side_w", (x0, x0 + 0.2, 0.22, height, z0, z1), facade)
    box(parts, tag + "side_e", (x1 - 0.2, x1, 0.22, height, z0, z1), facade)
    for side, front in (("north", False), ("south", True)):
        wall_z0, wall_z1 = (z1 - 0.2, z1) if front else (z0, z0 + 0.2)
        glass_z0, glass_z1 = (z1 + 0.005, z1 + 0.015) if front else (z0 - 0.015, z0 - 0.005)
        box(parts, tag + side + "_spandrel",
            (x0, x1, 0.22, 0.85, wall_z0, wall_z1), facade,
            repeat=(floors, (0, 3.2, 0)))
        box(parts, tag + side + "_header",
            (x0, x1, 2.85, 3.2, wall_z0, wall_z1), facade,
            repeat=(floors, (0, 3.2, 0)))
        box(parts, tag + side + "_glass",
            (x0 + 0.18, x1 - 0.18, 0.85, 2.85, glass_z0, glass_z1), site["glass"],
            repeat=(floors, (0, 3.2, 0)))
        bays = max(2, round(w / 2.2))
        pitch = (w - 0.4) / bays
        box(parts, tag + side + "_mullions",
            (x0 + 0.2, x0 + 0.25, 0.85, 2.85, glass_z0 - 0.025, glass_z1 + 0.025),
            "metal", repeat=((bays, (pitch, 0, 0)), (floors, (0, 3.2, 0))))
    box(parts, tag + "roof", (x0, x1, height, height + 0.22, z0, z1), "slate")
    for side, bounds in (("w", (x0, x0 + 0.18, z0, z1)),
                         ("e", (x1 - 0.18, x1, z0, z1)),
                         ("n", (x0, x1, z0, z0 + 0.18)),
                         ("s", (x0, x1, z1 - 0.18, z1))):
        a, b, c, d2 = bounds
        box(parts, tag + "parapet_" + side,
            (a, b, height + 0.22, height + 0.62, c, d2), facade)


def build(_: GenerationInput) -> Asset:
    validate_city_layout()
    materials = city_materials()
    parts: list[Part] = []
    roads(parts)
    for index, placement in enumerate(CITY["placements"]):
        kind = placement["blueprint"]
        start = len(parts)
        {"02-apartment": apartment, "03-convenience": convenience, "04-office": office}[kind](parts, placement)
        _vary_designed_building(parts, start, placement, index)
    sites = infill_sites()
    for site in sites:
        _infill_building(parts, site)
    site_furnishings(parts, CITY["placements"], [site["bounds"] for site in sites])
    return Asset(name="City", materials=materials, parts=tuple(parts),
                 extras={"tiled_materials": city_tile_specs(),
                         "infill_count": len(sites), "city_variation_seed": 91107})


asset = AssetGenerator(name="City", parameters={}, build=build, seed=1)
blueprint = "../blueprints/japan-realistic-v1/01-city/blueprint.json"
blueprint_dependencies = (
    "../blueprints/japan-realistic-v1/02-apartment/blueprint.json",
    "../blueprints/japan-realistic-v1/03-convenience/blueprint.json",
    "../blueprints/japan-realistic-v1/04-office/blueprint.json",
)
blueprint_part_map = {"ground": ("ground",), "curb": ("curb_standard",)}
blueprint_prototype_parts = ("curb",)
blueprint_envelope_mode = "height_maximum"
blueprint_texel_parts = ("site_" + CITY["placements"][0]["id"] + "_side_w",)
blueprint_required_parts = tuple(f"site_{placement['id']}_foundation" for placement in CITY["placements"])
render = RenderSettings(
    resolution=768, aspect_ratio=1.6, views=(), passes=("shaded",), samples=24,
    environment="sunny",
    cameras=(
        Camera("district_oblique", position=(440, 440, 440), target=(0, 0, 0), fov=math.radians(55)),
        Camera("district_plan", position=(0, 700, 0.001), target=(0, 0, 0), orthographic=True, ortho_scale=520),
        Camera("main_street", position=(0, 2.0, 55), target=(0, 2.0, -85), fov=math.radians(70)),
        Camera("neighborhood_walk", position=(-65, 2.0, -20), target=(-65, 8, -75),
               fov=math.radians(70)),
    ),
)
