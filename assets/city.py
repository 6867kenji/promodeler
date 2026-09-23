"""Shiomi 500 m district, generated from the 01-city placement and road plan.

The three building functions are reusable shells with walkable floor plates,
entrances and fixed interior zones.  Site placement is always read from the
numerical blueprint; the concept sheet is used only for visual review.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

from promodeler.core import (
    Array, Asset, AssetGenerator, Box, Camera, Cylinder, GenerationInput,
    Material, ModelingError, Part, RenderSettings, Sphere, Transform, srgb,
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
        for segment, (start, end) in enumerate(_street_segments()):
            for side in (-1, 1):
                z0, z1 = (center - half, center - carriage) if side < 0 else (center + carriage, center + half)
                x0, x1 = (center - half, center - carriage) if side < 0 else (center + carriage, center + half)
                box(parts, f"walk_ew_{road_index}_{segment}_{side}",
                    (start, end, 0, 0.15, z0, z1), "concrete")
                box(parts, f"walk_ns_{road_index}_{segment}_{side}",
                    (x0, x1, 0, 0.15, start, end), "concrete")
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
    # Open stair cores flank the main body; the treads remain separate meshes.
    for side, left in (("w", -15.0), ("e", 12.0)):
        b(f"stair_{side}_outside", (left, left + 0.2, 0, 18, -7, 1), "concrete")
        b(f"stair_{side}_inside", (left + 2.8, left + 3, 0, 18, -7, 1), "concrete")
        b(f"stair_{side}_back", (left, left + 3, 0, 18, -7, -6.8), "concrete")
        b(f"stair_{side}_landings", (left, left + 3, 0, 0.2, -7, 1), "concrete", floors)
        b(f"stair_{side}_flight_a", (left + 0.3, left + 1.5, 0.006667, 0.166667, -5.4, -5.12),
          "concrete", ((9, (0, 0.166667, 0.28)), (5, (0, 3, 0))))
        b(f"stair_{side}_flight_b", (left + 1.5, left + 2.7, 1.506667, 1.666667, -3.16, -2.88),
          "concrete", ((9, (0, 0.166667, -0.28)), (5, (0, 3, 0))))
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
    b("sales_floor", (-8.85, 8.85, 0, 0.06, -5.85, 5.85), "tile")
    b("roof", (-9, 9, 4.02, 4.2, -6, 6), "slate")
    b("wall_n", (-9, 9, 0, 4.02, -6, -5.85))
    b("wall_w", (-9, -8.85, 0, 4.02, -6, 6))
    b("wall_e", (8.85, 9, 0, 4.02, -6, 6))
    b("south_sill", (-9, 9, 0, 0.15, 5.85, 6), "tile")
    b("front_glass_left", (-8.85, -0.9, 0.15, 2.8, 5.97, 5.98), "glass")
    b("front_glass_right", (0.9, 8.85, 0.15, 2.8, 5.97, 5.98), "glass")
    b("entry_left", (-0.9, 0, 0.15, 2.35, 5.96, 5.98), "glass")
    b("entry_right", (0, 0.9, 0.15, 2.35, 5.96, 5.98), "glass")
    b("front_mullions", (-8.27, -8.23, 0.15, 2.8, 5.95, 6), "metal", repeat=(12, (1.5, 0, 0)))
    b("sign_band", (-9, 9, 3.05, 3.7, 5.96, 6), "teal")
    b("roof_fascia", (-9, 9, 3.7, 4.2, 5.86, 6), "paint")
    b("backroom_wall_l", (-8.85, 5.8, 0.06, 2.8, -2.9, -2.8), "paint")
    b("backroom_wall_r", (5.9, 8.85, 0.06, 2.8, -2.9, -2.8), "paint")
    b("toilet_wall", (5.8, 5.9, 0.06, 2.8, -5.85, -2.9), "paint")
    b("checkout", (-7.6, -4.0, 0, 0.9, 3.325, 4.075), "paint")
    b("checkout_top", (-7.62, -3.98, 0.88, 0.92, 3.3, 4.1), "slate")
    b("cold_wall", (-5.4, 5.4, 0, 2.1, -2.55, -1.75), "metal")
    b("cold_glass", (-5.36, 5.36, 0.25, 2, -1.75, -1.74), "glass")
    for shelf, x in enumerate((-3.0, 0.0, 3.0)):
        b(f"shelf_{shelf}_boards", (x - 0.45, x + 0.45, 0.15, 0.175, -1.3, 2.3),
          "paint", repeat=(5, (0, 0.3, 0)))
        b(f"shelf_{shelf}_left", (x - 0.45, x - 0.425, 0, 1.5, -1.3, 2.3), "metal")
        b(f"shelf_{shelf}_right", (x + 0.425, x + 0.45, 0, 1.5, -1.3, 2.3), "metal")
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


def site_furnishings(parts: list[Part], placements: list[dict]) -> None:
    # Two planted trees per lot. Offsets stay inside each 50 m site and outside roofs.
    for placement in placements:
        x, _, z = placement["position_m"]
        extent_x, _, extent_z = BUILDINGS[placement["blueprint"]]["dimensions"]["envelope_xyz_m"]
        for side in (-1, 1):
            tx = x + side * (extent_x / 2 + 4.0)
            tz = z + (-12.0 if placement["blueprint"] == "03-convenience" else 12.0)
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
    )


def build(_: GenerationInput) -> Asset:
    validate_city_layout()
    materials = city_materials()
    parts: list[Part] = []
    roads(parts)
    for placement in CITY["placements"]:
        kind = placement["blueprint"]
        {"02-apartment": apartment, "03-convenience": convenience, "04-office": office}[kind](parts, placement)
    site_furnishings(parts, CITY["placements"])
    return Asset(name="City", materials=materials, parts=tuple(parts))


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
blueprint_texel_parts = ()  # Shared solid materials: no large unique 500 m texture atlas.
blueprint_required_parts = tuple(f"site_{placement['id']}_foundation" for placement in CITY["placements"])
render = RenderSettings(
    resolution=768, aspect_ratio=1.6, views=(), passes=("shaded",), samples=24,
    environment="sunny",
    cameras=(
        Camera("district_oblique", position=(440, 440, 440), target=(0, 0, 0), fov=math.radians(55)),
        Camera("district_plan", position=(0, 700, 0.001), target=(0, 0, 0), orthographic=True, ortho_scale=520),
        Camera("main_street", position=(0, 2.0, 55), target=(0, 2.0, -85), fov=math.radians(70)),
    ),
)
