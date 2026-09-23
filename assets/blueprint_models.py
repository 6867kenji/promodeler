"""Entry point for the remaining non-character design sheets."""

from __future__ import annotations

import json
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
                          hide_parts=("closure_shutter",)),)
        lights = tuple(Light(f"stair-{i}", position=(0, -0.8 - i * 1.35,
                                                     -7 + i * 2.8), energy=700, size=2.5)
                       for i in range(4))
    elif number == 18:
        cameras = (Camera("walkthrough", position=(0, 1.65, -43),
                          target=(0, 1.4, -7)),)
        lights = tuple(Light(f"hall-{z}", position=(0, 2.8, z), energy=1100, size=6)
                       for z in range(-42, 43, 12))
    elif number == 19:
        cameras = (Camera("walkthrough", position=(0, 1.7, -59),
                          target=(0, 1.55, -20)),)
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
    settings = (RenderSettings(resolution=512, views=("perspective", "front", "side"), passes=("shaded",),
                               environment="studio", samples=24)
                if number in PROP_NUMBERS else
                _space_render(number) if number >= 17 else
                RenderSettings(resolution=768, aspect_ratio=1.6, views=("perspective", "front"),
                               passes=("shaded",), environment="sunny", samples=24))
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
