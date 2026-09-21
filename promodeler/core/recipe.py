"""Versioned JSON recipe: the exact, closed input the kernel compiles.

The recipe is the cache key material. It contains everything that
influences the output and nothing else: no file paths, no timestamps.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from .asset import Asset, ExportSettings, GenerationInput, RenderSettings
from .diagnostics import ModelingError

RECIPE_VERSION = 1


def build_recipe(
    asset: Asset,
    input: GenerationInput | None = None,
    render: RenderSettings | None = None,
    parameters: Any = None,
    generator_version: int | None = None,
    export: ExportSettings | None = None,
) -> dict:
    render = render or RenderSettings()
    render.validate()
    export = export or ExportSettings()
    export.validate()
    if render.pose is not None and render.pose not in asset.pose_ids():
        raise ModelingError("render.pose", f"render.pose {render.pose!r} is not a pose of the asset.")
    recipe: dict = {
        "recipe_version": RECIPE_VERSION,
        "asset": asset.to_recipe(),
        "render": render.to_recipe(),
        "export": export.to_recipe(),
    }
    if input is not None:
        recipe["input"] = {
            "seed": input.seed,
            "quality": input.quality.to_recipe(),
            "parameters": parameters,
        }
        if generator_version is not None:
            recipe["input"]["generator_version"] = generator_version
    return recipe


def dump_recipe(recipe: dict) -> str:
    """Canonical JSON: sorted keys, no insignificant whitespace, ASCII-safe."""
    return json.dumps(recipe, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)


def recipe_hash(recipe: dict, **environment: Any) -> str:
    """SHA-256 over the canonical recipe plus environment facts such as kernel and Blender versions."""
    payload = {"recipe": recipe, "environment": dict(sorted(environment.items()))}
    return hashlib.sha256(dump_recipe(payload).encode("ascii")).hexdigest()
