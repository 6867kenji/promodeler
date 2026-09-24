"""Entry point for the remaining non-character design sheets."""

from __future__ import annotations

import json
import math
from pathlib import Path

from promodeler.core import AssetGenerator, Camera, Light, RenderSettings

from assets.blueprint_props import FOCAL_TEXTURE_PARTS, build_prop, joint_id


ROOT = Path(__file__).resolve().parent.parent / "blueprints" / "japan-realistic-v1"
PROP_NUMBERS = range(7, 17)


def load_design(folder: str) -> dict:
    return json.loads((ROOT / folder / "blueprint.json").read_text(encoding="utf-8"))


def _space_render(number: int) -> RenderSettings:
    if number == 17:
        cameras = (Camera("walkthrough", position=(0, 1.65, -12.8),
                          target=(0, -3.1, -1.5),
                          hide_parts=("closure_shutter",)),
                   Camera("escalator_close", position=(1.65, 1.4, -11.3),
                          target=(1.65, -2.7, -3.2), fov=math.radians(66),
                          hide_parts=("closure_shutter", "canopy-frame",
                                      "lower_hall_ceiling")),
                   Camera("glass_side", position=(4.1, 1.45, -9.7),
                          target=(0.7, -2.6, -3.0), fov=math.radians(64),
                          hide_parts=("canopy-frame", "lift-shaft",
                                      "lower_hall_ceiling")))
        lights = tuple(Light(f"stair-{i}", position=(0, -0.8 - i * 1.35,
                                                     -7 + i * 2.8), energy=700, size=2.5)
                       for i in range(4))
    elif number == 18:
        cameras = (Camera("walkthrough", position=(0, 1.65, -35),
                          target=(0, 1.3, -27)),
                   Camera("gate_oblique", position=(0, 4.3, -34),
                          target=(0, 0.5, -28), fov=math.radians(63),
                          hide_parts=("ceiling",)),
                   Camera("gate_full_width", position=(0, 6.2, -41),
                          target=(0, 0.7, -28), fov=math.radians(80),
                          hide_parts=("ceiling",)),
                   Camera("gate_plan", position=(0, 14, -28),
                          target=(0, 0.3, -28), fov=math.radians(60),
                          hide_parts=("ceiling",)),
                   Camera("staff_room", position=(-3.35, 1.75, -25.7),
                          target=(-6.9, 0.9, -28.3), fov=math.radians(72),
                          hide_parts=("ceiling",)),
                   Camera("tactile_detail", position=(3.6, 1.45, -31),
                          target=(3.08, 0.1, -29), fov=math.radians(55),
                          hide_parts=("ceiling",)))
        lights = tuple(Light(f"hall-{z}", position=(0, 2.8, z), energy=1100, size=6)
                       for z in range(-42, 43, 12))
    elif number == 19:
        cameras = (Camera("walkthrough", position=(0, 1.7, -59),
                          target=(0, 1.55, -20)),
                   Camera("floor_detail", position=(1.8, 1.55, -49),
                          target=(3.65, 0.05, -44), fov=math.radians(58)))
        lights = tuple(Light(f"platform-{z}", position=(0, 3.45, z),
                             energy=1100, size=5) for z in range(-60, 61, 12))
    elif number == 20:
        cameras = (Camera("cutaway", position=(8, 7, 9), target=(0, 0.3, 0),
                          hide_parts=("roof", "ceiling", "side_wall_1",
                                      "front_window_e", "roof_parapet_e")),)
        lights = tuple(Light(f"cafe-{x}-{z}", position=(x, 2.65, z),
                             energy=70, size=2.0) for x in (-2.7, 2.7)
                       for z in (-2.0, 2.0))
    else:
        cameras = (Camera("cutaway", position=(9, 7.5, 12), target=(0, 0.2, 0),
                          hide_parts=("tenant-roof", "ceiling", "side_wall_1",
                                      "front_window_e")),)
        lights = tuple(Light(f"dojo-{x}-{z}", position=(x, 2.85, z),
                             energy=55, size=2.4) for x in (-3, 0, 3)
                       for z in (-4, 0, 4))
    return RenderSettings(resolution=768, aspect_ratio=1.6,
                          views=("perspective", "front"), cameras=cameras,
                          lights=lights, passes=("shaded",),
                          environment="overcast" if number <= 19 else "studio", samples=32)


def definition(folder: str) -> dict:
    design = load_design(folder)
    number = int(folder[:2])
    if number in PROP_NUMBERS:
        generate = lambda _input: build_prop(design, folder)
    elif number in (2, 3, 4):
        from assets.blueprint_architecture import build_architecture
        generate = lambda _input: build_architecture(design, folder)
    elif number in (17, 18, 19, 20, 21):
        from assets.blueprint_spaces import build_space
        generate = lambda _input: build_space(design, folder)
    else:
        raise ValueError(f"No non-character generator for {folder!r}.")
    texel_parts = FOCAL_TEXTURE_PARTS.get(folder, ())
    part_map = {part["id"]: (part["id"],) for part in design["parts"]}
    if number in (2, 3, 4):
        from assets.blueprint_architecture import part_map_for
        part_map = part_map_for(folder)
        texel_parts = ()
    elif number == 20:
        for expected in design["parts"]:
            pid = expected["id"]
            if pid.startswith("table-"):
                part_map[pid] = tuple(pid + suffix for suffix in ("_top", "_stem", "_base"))
            elif pid.startswith("chair-"):
                part_map[pid] = (pid + "_seat", pid + "_back") + tuple(
                    f"{pid}_leg_{ix}_{iz}" for ix in range(2) for iz in range(2))
    elif number == 21:
        for pid in ("bag-0", "bag-1"):
            part_map[pid] = (pid, pid + "_base")
    settings = (RenderSettings(resolution=512, views=("perspective", "front", "side"), passes=("shaded",),
                               environment="studio", samples=24)
                if number in PROP_NUMBERS else
                _space_render(number) if number >= 17 else
                RenderSettings(resolution=768, aspect_ratio=1.6, views=("perspective", "front"),
                               passes=("shaded",), environment="sunny", samples=24,
                               cameras=(
                                   Camera("balcony_left", position=(-27, 11, 23),
                                          target=(-9, 9, 7.5), fov=math.radians(55)),
                                   Camera("rear_stairs", position=(0, 10, -38),
                                          target=(0, 9, -5), fov=math.radians(58)),
                                   Camera("west_stair", position=(-13.5, 7, -13),
                                          target=(-13.5, 7, -3), fov=math.radians(65)),
                               ) if number == 2 else (
                                   Camera("cutaway", position=(13, 10, 14),
                                          target=(0, 1, -0.5), fov=math.radians(60),
                                          hide_parts=("site_standalone_roof",
                                                      "site_standalone_wall_e",
                                                      "site_standalone_front_glass_right",
                                                      "site_standalone_roof_fascia",
                                                      "site_standalone_right_cooler_back",
                                                      "site_standalone_right_cooler_end_s")),
                                   Camera("store_entry", position=(1.45, 1.7, 5.4),
                                          target=(1.45, 1.25, -2.0), fov=math.radians(72),
                                          hide_parts=("site_standalone_roof",)),
                                   Camera("entry_front", position=(0, 2.25, 13.0),
                                          target=(0, 1.45, 5.95), fov=math.radians(48)),
                                   Camera("sales_plan", position=(0, 18, 1.0),
                                          target=(0, 0.6, 1.0), fov=math.radians(62),
                                          hide_parts=("site_standalone_roof",)),
                                   Camera("cooler_aisle", position=(5.3, 1.65, 3.5),
                                          target=(8.3, 1.1, 0.5), fov=math.radians(66),
                                          hide_parts=("site_standalone_roof",)),
                                   Camera("exterior_tile", position=(17, 5, 13),
                                          target=(8, 2, 0), fov=math.radians(54)),
                               ) if number == 3 else ()))
    return {
        "asset": AssetGenerator(name=design["id"], parameters={}, build=generate, seed=number),
        "blueprint": f"../blueprints/japan-realistic-v1/{folder}/blueprint.json",
        "blueprint_part_map": part_map,
        "blueprint_motion_map": {motion["id"]: joint_id(motion["id"]) for motion in design.get("motions", [])},
        "blueprint_texel_parts": texel_parts,
        "blueprint_envelope_mode": (
            "maximum" if number in (10, 12, 15, 16) else
            "scheduled" if number == 21 else "exact"
        ),
        "render": settings,
    }
