"""M5 example: a displaced rock with scattered pebbles, grass tufts as fur, and two LODs.

Run:  python -m promodeler build assets/mossy_rock.py --formats glb,usdz
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from promodeler.core import (
    LOD, Asset, AssetGenerator, Displace, Facing, Fur, GenerationInput, Material, ModelingError, Noise, Part,
    RenderSettings, Scatter, Sphere, Subdivision, presets, srgb,
)


@dataclass(frozen=True)
class RockParameters:
    radius: float = 0.25
    grass: float = 1.0


def validate(p: RockParameters) -> None:
    if not 0.05 <= p.radius <= 2.0:
        raise ModelingError("rock.radius", "radius must be 5 cm...2 m.")
    if not 0.0 <= p.grass <= 3.0:
        raise ModelingError("rock.grass", "grass must be 0...3.")


def build(input: GenerationInput) -> Asset:
    p: RockParameters = input.parameters
    stone = presets.concrete("stone", color=srgb(0.5, 0.48, 0.44), seed=input.seed, staining=0.8)
    pebble = Material("pebble", base_color=srgb(0.42, 0.4, 0.37), roughness=0.85)
    grass = Material("grass", base_color=srgb(0.32, 0.45, 0.14), roughness=0.7)
    r = p.radius
    shape_noise = (Noise(size=r * 1.2, detail=2.0, roughness=0.5, seed=input.seed) - 0.5) * (r * 0.5) \
        + (Noise(size=r * 0.25, detail=4.0, roughness=0.6, seed=input.seed + 1) - 0.5) * (r * 0.12)
    rock = Part(
        id="rock",
        shape=Sphere(radius=r, segments=48, rings=32),
        material="stone",
        modifiers=(Subdivision(levels=1), Displace(height=shape_noise)),
        smooth_angle=math.radians(40),
        lods=(LOD(distance=5.0, ratio=0.3), LOD(distance=15.0, ratio=0.08)),
    )
    up = Facing((0.0, 1.0, 0.0))
    pebbles = Part(
        id="pebbles",
        shape=Scatter(surface="rock", instance=Sphere(radius=r * 0.05, segments=10, rings=6), density=120.0 / (r * r),
                      seed=input.seed + 3, scale=(0.4, 1.3), mask=up.smoothstep(0.5, 0.9)),
        material="pebble",
        smooth_angle=math.radians(50),
    )
    tufts = Part(
        id="grass",
        shape=Fur(surface="rock", density=600.0 * p.grass / (r * r), length=r * 0.16, thickness=r * 0.005,
                  segments=4, sides=3, droop=0.8, curl=0.5, seed=input.seed + 4, mask=up.smoothstep(0.55, 0.95)),
        material="grass",
    )
    return Asset(name="Mossy rock", materials=(stone, pebble, grass), parts=(rock, pebbles, tufts))


asset = AssetGenerator(name="Mossy rock", parameters=RockParameters(), build=build, validate=validate, seed=11)
render = RenderSettings(resolution=640, views=("perspective", "front"), passes=("shaded", "clay"), environment="overcast")
