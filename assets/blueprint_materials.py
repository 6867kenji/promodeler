"""Small, repeatable PBR palettes derived from the numerical design colors.

Broad building surfaces use constants so a single large face does not claim a
misleading 512 px/m unique map.  Visible furniture, upholstery and electronics
receive per-part baked color, roughness and bump maps.
"""

from __future__ import annotations

import math

from promodeler.core import Bricks, Color, ColorRamp, Layer, Material, Noise, srgb


TEXTURED = {
    "oak", "wood", "fabric", "case-coat", "shell-plastic", "keycap",
    "dark-screen", "rgb-diffuser", "eva-blue", "eva-charcoal", "vinyl",
    "rubber", "wall-tile", "floor-tile", "tile", "plaster",
}


def color_from_hex(value: str):
    code = value.lstrip("#")
    if len(code) != 6:
        raise ValueError(f"Expected six-digit sRGB hex color, got {value!r}")
    return srgb(*(int(code[i:i + 2], 16) / 255 for i in (0, 2, 4)))


def materials_for(design: dict, *, include_surface_maps: bool = True,
                  textured_ids: set[str] | None = None) -> tuple[Material, ...]:
    out = []
    for index, spec in enumerate(design["materials"]):
        mid = spec["id"]
        color = color_from_hex(spec["base_color_srgb"])
        rough = spec.get("roughness", [0.5, 0.5])
        midpoint = sum(rough) / 2 if isinstance(rough, list) else float(rough)
        metallic = spec.get("metallic", 0)
        if isinstance(metallic, list):
            metallic = sum(metallic) / 2
        textured = include_surface_maps and mid in TEXTURED and (textured_ids is None or mid in textured_ids)
        if mid in {"glass", "frosted-glass"}:
            out.append(Material(mid, base_color=Color(color.r, color.g, color.b, 0.10 if mid == "glass" else 0.48),
                                roughness=midpoint, alpha_mode="blend"))
        elif mid == "mirror":
            out.append(Material(mid, base_color=color, metallic=1, roughness=midpoint))
        elif mid in {"opal", "light"}:
            out.append(Material(mid, base_color=color, roughness=midpoint,
                                emission_color=color, emission_strength=1.8))
        elif mid == "rgb-diffuser":
            grain = Noise(size=0.008, detail=1.0, seed=index + 101)
            out.append(Material(mid, base_color=ColorRamp(grain, ((0.2, color.scaled(0.8)),
                                                                    (0.8, color.scaled(1.08)))),
                                roughness=midpoint, emission_color=color, emission_strength=2.0))
        elif mid in {"oak", "wood"} and textured:
            long_grain = Noise(size=(0.008, 0.008, 0.6), detail=4, roughness=0.55, seed=index + 21)
            out.append(Material(mid,
                                base_color=ColorRamp(long_grain, ((0.2, color.scaled(0.78)),
                                                                  (0.55, color), (0.85, color.scaled(1.12)))),
                                roughness=midpoint - 0.04 + long_grain * 0.08,
                                height=long_grain * 0.00008, bump_strength=1.1))
        elif mid in {"fabric", "eva-blue", "eva-charcoal", "vinyl", "rubber"} and textured:
            grain = Noise(size=0.0015 if mid == "fabric" else 0.0035, detail=3,
                          roughness=0.6, seed=index + 31)
            amplitude = 0.00016 if mid == "fabric" else 0.00025
            out.append(Material(mid,
                                base_color=ColorRamp(grain, ((0.2, color.scaled(0.9)),
                                                              (0.8, color.scaled(1.06)))),
                                roughness=max(0.05, midpoint - 0.04) + grain * 0.08,
                                height=grain * amplitude, bump_strength=1.0))
        elif mid in {"wall-tile", "floor-tile", "tile"} and textured:
            pitch = 0.095 if mid == "wall-tile" else 0.3
            joint = Bricks(width=pitch, height=0.045 if mid == "wall-tile" else pitch,
                           mortar=0.005 if mid == "wall-tile" else 0.003, axis="y")
            tone = Noise(size=pitch, detail=1.0, seed=index + 42)
            out.append(Material(mid,
                                base_color=ColorRamp(tone, ((0.2, color.scaled(0.97)),
                                                             (0.8, color.scaled(1.03)))),
                                roughness=midpoint, height=-joint * 0.0015,
                                layers=(Layer(base_color=color.scaled(0.75), mask=joint),),
                                bump_strength=1.0))
        elif mid in {"case-coat", "shell-plastic", "keycap", "dark-screen", "plaster"} and textured:
            grain = Noise(size=0.005 if mid != "plaster" else 0.002, detail=2,
                          roughness=0.55, seed=index + 61)
            out.append(Material(mid,
                                base_color=ColorRamp(grain, ((0.2, color.scaled(0.96)),
                                                              (0.8, color.scaled(1.04)))),
                                roughness=midpoint - 0.02 + grain * 0.04,
                                height=grain * (0.00008 if mid != "plaster" else 0.00015),
                                emission_color=color if mid == "dark-screen" else srgb(0, 0, 0),
                                emission_strength=0.15 if mid == "dark-screen" else 0,
                                bump_strength=0.8))
        else:
            out.append(Material(mid, base_color=color, roughness=midpoint, metallic=metallic))
    return tuple(out)


def texture_resolution_for(size: tuple[float, float, float], *, maximum: int = 4096) -> int:
    """About 800 source pixels/m on a face before UV packing losses."""
    target = max(size) * 800
    power = 2 ** math.ceil(math.log2(max(256, target)))
    return min(maximum, max(256, power))
