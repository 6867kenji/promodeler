"""Reusable procedural material recipes. Each returns a ``Material`` you can further customize.

They follow the layered recipe used in texturing tools: a base with
micro-variation, then masked layers for edge wear, cavity dirt and
accumulated grime. Sizes are meters, so they read correctly on any asset.

``edge_radius`` drives the edge-wear curvature probe. It must exceed the
geometric bevel width of the part by about three times, otherwise rounded
edges look flat to the probe and no wear appears.
"""

from __future__ import annotations

from .color import Color, srgb
from .fields import Cavity, ColorRamp, Curvature, Facing, Noise, Voronoi
from .material import Layer, Material


def worn_leather(
    id: str = "leather", color: Color = srgb(0.36, 0.20, 0.11), seed: int = 0, wear: float = 1.0,
    edge_radius: float = 0.006,
) -> Material:
    """Full-grain leather with pores, creases, polished edges and dirt in the seams."""
    grain = Voronoi(size=0.0018, feature="distance_to_edge", randomness=1.0, seed=seed).smoothstep(0.0, 0.5)
    pores = Noise(size=0.0035, detail=6.0, roughness=0.65, seed=seed + 1)
    creases = Noise(size=(0.06, 0.005, 0.06), detail=4.0, roughness=0.6, seed=seed + 2).smoothstep(0.35, 0.75)
    mottle = Noise(size=0.035, detail=4.0, roughness=0.55, seed=seed + 3)
    scuffs = Noise(size=(0.08, 0.004, 0.08), detail=2.0, roughness=0.4, seed=seed + 4).smoothstep(0.55, 0.78)
    fine = Noise(size=0.012, detail=5.0, roughness=0.6, seed=seed + 5)

    base_color = ColorRamp(mottle * 0.7 + fine * 0.3, ((0.2, color.scaled(0.62)), (0.55, color), (0.85, color.scaled(1.18))))
    roughness = 0.48 + pores * 0.28 - creases * 0.1 + fine * 0.08
    height = grain * 0.00016 + pores * 0.00025 + creases * 0.0011

    edge_band = Curvature(radius=edge_radius).smoothstep(0.12, 0.65)
    edge_wear = Layer(
        base_color=color.scaled(1.7),
        roughness=0.34,
        height=0.0,
        mask=(edge_band * (0.55 + 0.45 * mottle) * wear).clamp(),
    )
    seam_dirt = Layer(
        base_color=color.scaled(0.4),
        roughness=0.88,
        mask=(Cavity(distance=0.008) * 0.9).clamp(),
    )
    scuffed = Layer(
        base_color=color.scaled(1.35),
        roughness=0.42,
        mask=(scuffs * 0.6 * wear).clamp(),
    )
    return Material(
        id, base_color=base_color, roughness=roughness, metallic=0.0, height=height,
        layers=(seam_dirt, scuffed, edge_wear), bump_strength=1.2,
    )


def rusty_iron(id: str = "iron", seed: int = 0, rust: float = 0.5, edge_radius: float = 0.004) -> Material:
    """Machined iron with patchy rust that gathers in crevices and runs down walls, and bright worn edges."""
    machining = Noise(size=(0.03, 0.0005, 0.03), detail=4.0, roughness=0.5, seed=seed)
    speckle = Noise(size=0.004, detail=6.0, roughness=0.6, seed=seed + 1)
    patches = Noise(size=0.045, detail=5.0, roughness=0.55, seed=seed + 2)
    rust_tone = Noise(size=0.007, detail=6.0, roughness=0.6, seed=seed + 3)
    pitting = Voronoi(size=0.0025, feature="f1", seed=seed + 4)
    streak_noise = Noise(size=(0.004, 0.07, 0.004), detail=3.0, roughness=0.5, seed=seed + 5)
    flakes = Noise(size=0.0015, detail=4.0, roughness=0.7, seed=seed + 6)

    base_color = ColorRamp(speckle, ((0.3, srgb(0.5, 0.5, 0.52)), (0.7, srgb(0.62, 0.62, 0.64))))
    roughness = 0.32 + machining * 0.2 + speckle * 0.1
    height = machining * 0.00006

    threshold = 0.72 - 0.36 * rust
    detail = patches * 0.62 + speckle * 0.26 + flakes * 0.12
    sides = 1.0 - Facing((0.0, 1.0, 0.0))
    streaks = streak_noise.smoothstep(0.52, 0.66) * sides * (0.3 + 0.7 * rust)
    core = (detail.smoothstep(threshold, threshold + 0.06) + Cavity(distance=0.008) * (0.3 + 0.5 * rust) + streaks).clamp()
    deep = detail.smoothstep(threshold + 0.05, threshold + 0.2)
    halo = (detail.smoothstep(threshold - 0.1, threshold + 0.02) - core).clamp()

    rust_color = ColorRamp(rust_tone * 0.7 + flakes * 0.3, (
        (0.0, srgb(0.17, 0.07, 0.03)), (0.45, srgb(0.4, 0.16, 0.06)), (0.8, srgb(0.6, 0.29, 0.1)), (1.0, srgb(0.78, 0.46, 0.22)),
    ))
    rusted = Layer(
        base_color=rust_color,
        metallic=0.0,
        roughness=0.86 + flakes * 0.12,
        height=(1.0 - pitting).pow(3.0) * (0.25 + 0.75 * deep) * flakes * 0.0012 + flakes * 0.00035 + rust_tone * 0.00025,
        mask=core,
    )
    stained = Layer(
        base_color=ColorRamp(rust_tone, ((0.0, srgb(0.36, 0.26, 0.2)), (1.0, srgb(0.48, 0.34, 0.24)))),
        metallic=0.2,
        roughness=0.62,
        mask=halo,
    )
    dust = Layer(
        base_color=srgb(0.58, 0.53, 0.45),
        metallic=0.0,
        roughness=0.95,
        mask=(Facing((0.0, 1.0, 0.0)).pow(2.0) * patches * 0.55).clamp(),
    )
    edge_wear = Layer(
        base_color=srgb(0.78, 0.78, 0.8),
        metallic=1.0,
        roughness=0.2,
        height=0.0,
        mask=(Curvature(radius=edge_radius).smoothstep(0.15, 0.7) * (0.55 + 0.45 * speckle)).clamp(),
    )
    return Material(
        id, base_color=base_color, roughness=roughness, metallic=1.0, height=height,
        layers=(stained, rusted, dust, edge_wear), bump_strength=1.5,
    )


def painted_metal(
    id: str = "paint", color: Color = srgb(0.72, 0.16, 0.12), seed: int = 0, wear: float = 0.6,
    edge_radius: float = 0.005,
) -> Material:
    """Enamel paint over steel with chips on the edges and grime in recesses."""
    orange_peel = Noise(size=0.0025, detail=5.0, roughness=0.6, seed=seed)
    chips = Noise(size=0.012, detail=5.0, roughness=0.7, seed=seed + 1)
    grime = Noise(size=0.03, detail=4.0, seed=seed + 2)
    base_color = ColorRamp(grime, ((0.3, color.scaled(0.9)), (0.7, color)))
    chipped = Layer(
        base_color=srgb(0.55, 0.55, 0.58),
        metallic=1.0,
        roughness=0.35,
        height=-0.00012,
        mask=(Curvature(radius=edge_radius).smoothstep(0.1, 0.6) * (0.3 + 0.7 * chips) * 1.4 * wear).smoothstep(0.35, 0.6),
    )
    dirt = Layer(
        base_color=color.scaled(0.4),
        roughness=0.8,
        mask=(Cavity(distance=0.01) * 0.75).clamp(),
    )
    return Material(
        id, base_color=base_color, roughness=0.28 + orange_peel * 0.15, metallic=0.0,
        height=orange_peel * 0.00004, layers=(dirt, chipped), bump_strength=1.5,
    )
