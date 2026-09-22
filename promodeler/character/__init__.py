"""Humanoid characters as recipes, not meshes.

``promodeler.character`` turns a japan-realistic-v1 blueprint (or a
prompt, or a seed) into a ``CharacterRecipe``: a closed JSON document with
metric body measurements, semantic face and body sliders, appearance
colors and catalog IDs for hair, skin and wardrobe. A Unity project built
on UMA consumes the recipe (see docs/03-character-recipe-pipeline.md).
This package stays pure Python: no ``bpy``, no ``torch`` (the optional MHR
reference fit imports ``promodeler.human.mhr`` lazily).
"""

from .catalog import Catalog, CatalogEntry
from .recipe import (
    GENERATOR_VERSION, OUTFIT_SCHEMA, SCHEMA, CharacterRecipe, OutfitRecipe, RecipeWarning, canonical_dump, recipe_hash,
)

__all__ = [
    "Catalog", "CatalogEntry", "CharacterRecipe", "GENERATOR_VERSION", "OUTFIT_SCHEMA", "OutfitRecipe", "RecipeWarning",
    "SCHEMA", "canonical_dump", "recipe_hash",
]
