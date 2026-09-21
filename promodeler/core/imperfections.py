"""Height fields that break perfect regularity. Use them with ``Displace``.

Real objects are never exactly straight, round or flat. A few hundred
micrometers of wobble, a couple of dents and fine grain remove the
computer-generated look more than any texture. All sizes are meters.
"""

from __future__ import annotations

from .fields import Field, Noise, Voronoi


def wobble(size: float = 0.12, amplitude: float = 0.0015, seed: int = 0) -> Field:
    """Gentle large-scale waviness: a sheet that is not quite flat, a cylinder that is not quite round."""
    return (Noise(size=size, detail=1.5, roughness=0.4, seed=seed) - 0.5) * (2.0 * amplitude)


def dents(size: float = 0.03, depth: float = 0.004, coverage: float = 0.35, seed: int = 0) -> Field:
    """Sparse rounded dents. ``size`` is the cell size that spaces them, ``coverage`` the fraction of cells dented."""
    crater = 1.0 - Voronoi(size=size, feature="f1", randomness=1.0, seed=seed).smoothstep(0.15, 0.55)
    gate = Noise(size=size * 1.7, detail=1.0, roughness=0.3, seed=seed + 11).smoothstep(1.0 - coverage - 0.05, 1.0 - coverage + 0.05)
    return crater * gate * (-depth)


def grain(size: float = 0.0015, amplitude: float = 0.00012, seed: int = 0) -> Field:
    """Fine surface roughness in the geometry itself, for silhouettes and close-ups. Needs a dense mesh."""
    return (Noise(size=size, detail=3.0, roughness=0.6, seed=seed) - 0.5) * (2.0 * amplitude)


def ripples(size: float = 0.02, amplitude: float = 0.0006, seed: int = 0) -> Field:
    """Directional shallow waves, like hammered or rolled sheet metal."""
    return (Noise(size=(size, size * 0.15, size), detail=2.0, roughness=0.5, seed=seed) - 0.5) * (2.0 * amplitude)
