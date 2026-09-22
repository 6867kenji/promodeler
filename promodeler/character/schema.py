"""Generate and check the committed JSON Schema files from the recipe and catalog dataclasses.

``schemas/character_recipe.schema.json``, ``character_outfit.schema.json``
and ``asset_catalog.schema.json`` are generated; a test and
``promodeler character schema --check`` fail when the dataclasses and the
committed files drift apart. ``character_build.schema.json`` (the Unity
``build.json`` contract) is hand-written and only read here.
"""

from __future__ import annotations

import json
from pathlib import Path

from . import serialize
from .catalog import CatalogFile
from .recipe import CharacterRecipe, OutfitRecipe

SCHEMA_DIR = Path(__file__).resolve().parent.parent.parent / "schemas"
GENERATED = {
    "character_recipe": (CharacterRecipe, "CharacterRecipe", "A humanoid character for the promodeler Unity character creator (docs/03-character-recipe-pipeline.md)."),
    "character_outfit": (OutfitRecipe, "OutfitRecipe", "A wardrobe set applied to an existing character without changing its body."),
    "asset_catalog": (CatalogFile, "AssetCatalog", "One character/catalog/<category>.json file."),
}
HAND_WRITTEN = ("character_build",)


def generate(name: str) -> dict:
    cls, title, description = GENERATED[name]
    return serialize.schema(cls, f"https://promodeler.local/schemas/{name}.schema.json", title, description)


def render(name: str) -> str:
    return json.dumps(generate(name), indent=2, ensure_ascii=False) + "\n"


def write_all(directory: Path | str = SCHEMA_DIR) -> list[Path]:
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    written = []
    for name in GENERATED:
        path = directory / f"{name}.schema.json"
        path.write_text(render(name), encoding="utf-8")
        written.append(path)
    return written


def check_all(directory: Path | str = SCHEMA_DIR) -> list[str]:
    """Names of schema files that are missing or differ from the generated form."""
    directory = Path(directory)
    stale = []
    for name in GENERATED:
        path = directory / f"{name}.schema.json"
        if not path.is_file() or path.read_text(encoding="utf-8") != render(name):
            stale.append(name)
    for name in HAND_WRITTEN:
        if not (directory / f"{name}.schema.json").is_file():
            stale.append(name)
    return stale


def validate_with_jsonschema(data: dict, name: str) -> list[str]:
    """Cross-check against the committed schema when the optional ``jsonschema`` package is installed."""
    try:
        import jsonschema
    except ImportError:
        return []
    path = SCHEMA_DIR / f"{name}.schema.json"
    if not path.is_file():
        return [f"schema file missing: {path}"]
    validator = jsonschema.Draft202012Validator(json.loads(path.read_text(encoding="utf-8")))
    return [f"{'/'.join(str(p) for p in e.absolute_path) or '$'}: {e.message}" for e in sorted(validator.iter_errors(data), key=str)]
