"""``promodeler character ...`` and ``promodeler generate``: the CLI surface of the recipe layer.

Kept out of ``promodeler/cli.py`` so the asset CLI stays readable; that
module wires these parsers in.
"""

from __future__ import annotations

import json
import sys
from dataclasses import replace
from pathlib import Path

from ..core import ModelingError
from . import bridge, check, consistency, schema
from .catalog import Catalog
from .from_blueprint import character_from_blueprint, load_blueprint, outfit_from_blueprint
from .recipe import OUTFIT_SCHEMA, SCHEMA, CharacterRecipe, OutfitRecipe, RecipeWarning

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
RECIPES_DIR = PROJECT_ROOT / "character" / "recipes"
OUTFITS_DIR = PROJECT_ROOT / "character" / "outfits"


# --- files -----------------------------------------------------------------------------------

def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def resolve_recipe_path(target: str) -> Path:
    """An id under character/recipes or character/outfits, or a path to a recipe file."""
    candidate = Path(target)
    if candidate.is_file():
        return candidate
    for directory in (RECIPES_DIR, OUTFITS_DIR):
        path = directory / f"{target}.json"
        if path.is_file():
            return path
    raise ModelingError("character.recipe", f"No recipe or outfit named {target!r} (looked in character/recipes and character/outfits).")


def load_recipe(path: Path) -> CharacterRecipe | OutfitRecipe:
    data = json.loads(path.read_text(encoding="utf-8"))
    kind = data.get("schema")
    if kind == SCHEMA:
        return CharacterRecipe.from_json(data)
    if kind == OUTFIT_SCHEMA:
        return OutfitRecipe.from_json(data)
    raise ModelingError("recipe.schema", f"{path}: unknown schema {kind!r} (expected {SCHEMA} or {OUTFIT_SCHEMA}).")


def load_base_for(outfit: OutfitRecipe) -> CharacterRecipe | None:
    path = RECIPES_DIR / f"{outfit.base_character}.json"
    if not path.is_file():
        return None
    base = load_recipe(path)
    return base if isinstance(base, CharacterRecipe) else None


def print_warnings(warnings: list[RecipeWarning]) -> None:
    counts: dict[str, int] = {}
    for warning in warnings:
        counts[warning.code] = counts.get(warning.code, 0) + 1
    for warning in warnings:
        if warning.code == "catalog.placeholder":
            continue
        print(f"warning: {warning.code}: {warning.message}")
    if counts.get("catalog.placeholder"):
        print(f"warning: catalog.placeholder: {counts['catalog.placeholder']} references point at placeholder catalog entries (no content yet).")


# --- commands ----------------------------------------------------------------------------------

def generate_from_blueprint(blueprint_path: str, out: str | None, force: bool, seed: int | None) -> tuple[Path, list[RecipeWarning], str]:
    catalog = Catalog()
    blueprint = load_blueprint(blueprint_path)
    kind = blueprint.get("kind")
    if kind == "humanoid":
        recipe, warnings = character_from_blueprint(blueprint, catalog, seed=seed)
        warnings += recipe.validate(catalog)
        default_dir = RECIPES_DIR
    elif kind == "wearable":
        recipe, warnings = outfit_from_blueprint(blueprint, catalog)
        warnings += recipe.validate(catalog)
        default_dir = OUTFITS_DIR
    else:
        raise ModelingError("character.kind", f"{blueprint_path}: kind {kind!r} is not a character; write assets/<id>.py and use `promodeler build`.")
    path = Path(out) if out else default_dir / f"{recipe.id}.json"
    if path.exists() and not force:
        raise ModelingError("character.exists", f"{path} exists; the recipe is the source of truth. Use --force to regenerate or --out for another path.")
    write_json(path, recipe.to_json())
    return path, warnings, kind


def cmd_character_recipe(args) -> int:
    path, warnings, kind = generate_from_blueprint(args.blueprint, args.out, args.force, args.seed)
    print(f"{kind}: {path}")
    print_warnings(warnings)
    return 0


def cmd_character_validate(args) -> int:
    path = resolve_recipe_path(args.target)
    catalog = Catalog()
    recipe = load_recipe(path)
    if isinstance(recipe, OutfitRecipe):
        base = load_base_for(recipe)
        warnings = recipe.validate(catalog, base=base)
        if base is None:
            warnings.append(RecipeWarning("outfit.base", f"base character {recipe.base_character!r} has no recipe yet; race compatibility not checked."))
        schema_name = "character_outfit"
    else:
        warnings = recipe.validate(catalog)
        warnings += consistency.static_checks(recipe.body.measurements_m)
        schema_name = "character_recipe"
        if args.mhr:
            print("reference fit: running the MHR fit (torch on CPU, about 40 s on first run)...")
            fit = consistency.reference_fit(recipe, log=(print if args.verbose else None))
            recipe = consistency.with_reference_fit(recipe, fit)
            write_json(path, recipe.to_json())
            for key, residual in sorted(fit.residuals_m.items()):
                print(f"  {key:20s} {fit.measured_m.get(key, float('nan')):8.3f}  {residual * 1000:+7.1f} mm")
            print(f"reference fit written to {path} (body.reference_fit)")
    for problem in schema.validate_with_jsonschema(recipe.to_json(), schema_name):
        warnings.append(RecipeWarning("schema", problem))
    print(f"valid:    {path} ({recipe.schema})")
    print(f"hash:     {recipe.hash(catalog_version=catalog.version)[:12]}")
    print_warnings(warnings)
    print(f"warnings: {len(warnings)}")
    return 1 if args.strict and warnings else 0


def cmd_character_check(args) -> int:
    path = resolve_recipe_path(args.target)
    recipe = load_recipe(path)
    if not isinstance(recipe, CharacterRecipe):
        raise ModelingError("character.check", "check works on character recipes; outfits are checked through their base character.")
    build = check.load_build(args.build) if args.build else None
    if args.build and build is None:
        raise ModelingError("character.build", f"{args.build} has no build.json.")
    rows, budgets, warnings = check.compare(recipe, build)
    label = args.build if build else ("MHR reference fit" if recipe.body.reference_fit else "none (no Unity build yet; run `character validate --mhr` for a reference fit)")
    print(check.format_table(recipe, rows, budgets, warnings, label))
    return 0


def json_diff(old, new, path: str = "$") -> list[str]:
    if isinstance(old, dict) and isinstance(new, dict):
        lines = []
        for key in sorted(set(old) | set(new)):
            if key not in old:
                lines.append(f"{path}.{key}: (absent) -> {json.dumps(new[key], ensure_ascii=False)}")
            elif key not in new:
                lines.append(f"{path}.{key}: {json.dumps(old[key], ensure_ascii=False)} -> (absent)")
            else:
                lines += json_diff(old[key], new[key], f"{path}.{key}")
        return lines
    if isinstance(old, list) and isinstance(new, list) and len(old) == len(new):
        return [line for i, (a, b) in enumerate(zip(old, new)) for line in json_diff(a, b, f"{path}[{i}]")]
    if old != new:
        return [f"{path}: {json.dumps(old, ensure_ascii=False)} -> {json.dumps(new, ensure_ascii=False)}"]
    return []


def cmd_character_diff(args) -> int:
    path = resolve_recipe_path(args.target)
    current = load_recipe(path)
    source = current.source
    if source.kind != "blueprint" or not source.path:
        print(f"{path}: source is {source.kind}; nothing to regenerate against.")
        return 0
    catalog = Catalog()
    blueprint = load_blueprint(PROJECT_ROOT / source.path)
    regenerated, _ = (character_from_blueprint if isinstance(current, CharacterRecipe) else outfit_from_blueprint)(blueprint, catalog)
    old = current.to_json()
    new = regenerated.to_json()
    for volatile in ("source",):
        old.pop(volatile, None)
        new.pop(volatile, None)
    if isinstance(current, CharacterRecipe):
        old.get("body", {}).pop("reference_fit", None)
        new.get("body", {}).pop("reference_fit", None)
    lines = json_diff(old, new)
    print(f"recipe:    {path}")
    print(f"blueprint: {source.path}" + ("" if blueprint and source.sha256 == __import__('hashlib').sha256((PROJECT_ROOT / source.path).read_bytes()).hexdigest() else "  (blueprint changed since generation)"))
    if not lines:
        print("no differences: the recipe equals its regenerated form.")
        return 0
    print(f"{len(lines)} differences (recipe -> regenerated):")
    for line in lines:
        print(f"  {line}")
    return 0


def cmd_character_catalog(args) -> int:
    catalog = Catalog()
    entries = catalog.find(category=args.category, slot=args.slot, race=args.race)
    print(f"catalog version {catalog.version}, {len(catalog.entries)} entries, policy allows {list(catalog.policy.allowed)}")
    print(f"{'id':32s} {'category':12s} {'slots':18s} {'status':12s} {'license':10s} name")
    for entry in entries:
        print(f"{entry.id:32s} {entry.category:12s} {','.join(entry.slots):18s} {entry.runtime.status:12s} {entry.license.type:10s} {entry.name}")
    return 0


def cmd_character_schema(args) -> int:
    if args.write:
        for path in schema.write_all():
            print(f"written: {path}")
        return 0
    stale = schema.check_all()
    if stale:
        print(f"stale or missing schema files: {stale}. Run `promodeler character schema --write`.", file=sys.stderr)
        return 1
    print(f"schemas up to date in {schema.SCHEMA_DIR}")
    return 0


def cmd_character_build(args) -> int:
    path = resolve_recipe_path(args.target)
    recipe = load_recipe(path)
    catalog = Catalog()
    outfit = None
    if args.outfit:
        outfit = load_recipe(resolve_recipe_path(args.outfit))
        if not isinstance(outfit, OutfitRecipe):
            raise ModelingError("character.outfit", f"{args.outfit} is not an outfit recipe.")
    payload = {"recipe": recipe.to_json(), "outfit": outfit.to_json() if outfit else None}
    digest = recipe.hash(outfit=outfit.to_json() if outfit else None, catalog_version=catalog.version, unity=bridge.project_version(), uma=bridge.uma_version())
    out_dir = Path(args.out).resolve() / recipe.id / digest[:12]
    print(f"recipe:  {path}")
    print(f"hash:    {digest[:12]}")
    print(f"out:     {out_dir}")
    if not bridge.UNITY_PROJECT.is_dir():
        print(f"error:   Unity project not present at {bridge.UNITY_PROJECT} (planned for M10). The recipe and hash above are what it will receive.", file=sys.stderr)
        return 3
    try:
        unity = bridge.find_unity()
    except bridge.UnityNotFound as exc:
        print(f"error:   {exc}", file=sys.stderr)
        return 3
    out_dir.mkdir(parents=True, exist_ok=True)
    write_json(out_dir / "recipe.json", payload["recipe"])
    if payload["outfit"]:
        write_json(out_dir / "outfit.json", payload["outfit"])
    print(f"unity:   {unity}")
    print("error:   batch build is not implemented yet (M10); recipe.json was staged in the output directory.", file=sys.stderr)
    return 3


def cmd_generate(args) -> int:
    """Dispatch a blueprint by kind: characters go through the recipe layer, everything else is a hand-written asset."""
    blueprint = load_blueprint(args.blueprint)
    kind = blueprint.get("kind")
    if kind not in ("humanoid", "wearable"):
        print(f"{blueprint.get('id')}: kind {kind!r} is procedural. Write assets/{blueprint.get('id')}.py from the blueprint and run "
              f"`python -m promodeler build assets/{blueprint.get('id')}.py`.")
        return 2
    try:
        path, warnings, _ = generate_from_blueprint(args.blueprint, None, args.force, None)
        print(f"{kind}: {path}")
    except ModelingError as exc:
        if exc.code != "character.exists":
            raise
        path = resolve_recipe_path(blueprint["id"])
        print(f"{kind}: {path} (existing recipe kept; --force regenerates)")
        warnings = []
    print_warnings(warnings)
    if kind == "humanoid" and not args.no_build:
        args.target = blueprint["id"]
        args.outfit = None
        args.out = "build/character"
        return cmd_character_build(args)
    return 0


# --- parser wiring --------------------------------------------------------------------------------

def add_parsers(sub) -> None:
    generate = sub.add_parser("generate", help="Route a blueprint.json by kind: humanoid/wearable through the character recipe layer.")
    generate.add_argument("blueprint", help="Path to a promodeler-blueprint/1.0 blueprint.json.")
    generate.add_argument("--force", action="store_true", help="Regenerate an existing recipe.")
    generate.add_argument("--no-build", action="store_true", help="Stop after writing and validating the recipe.")
    generate.set_defaults(func=cmd_generate)

    character = sub.add_parser("character", help="Humanoid characters as recipes for the Unity character creator.")
    csub = character.add_subparsers(dest="character_command", required=True)

    recipe = csub.add_parser("recipe", help="Blueprint (humanoid or wearable) -> character/recipes|outfits/<id>.json.")
    recipe.add_argument("blueprint")
    recipe.add_argument("--out", default=None)
    recipe.add_argument("--force", action="store_true")
    recipe.add_argument("--seed", type=int, default=None)
    recipe.set_defaults(func=cmd_character_recipe)

    validate = csub.add_parser("validate", help="Schema, catalog, license and measurement-consistency checks (no Unity).")
    validate.add_argument("target", help="Recipe id or path.")
    validate.add_argument("--mhr", action="store_true", help="Also run the MHR reference fit (torch) and store body.reference_fit.")
    validate.add_argument("--strict", action="store_true", help="Exit 1 when there are warnings.")
    validate.add_argument("--verbose", "-v", action="store_true")
    validate.set_defaults(func=cmd_character_validate)

    chk = csub.add_parser("check", help="Blueprint targets vs recipe vs Unity build.json (or the MHR reference fit).")
    chk.add_argument("target")
    chk.add_argument("--build", default=None, help="build/character/<id>/<hash> directory with build.json.")
    chk.set_defaults(func=cmd_character_check)

    diff = csub.add_parser("diff", help="Differences between a recipe and its regeneration from the source blueprint.")
    diff.add_argument("target")
    diff.set_defaults(func=cmd_character_diff)

    catalog = csub.add_parser("catalog", help="List catalog entries.")
    catalog.add_argument("action", choices=("list",))
    catalog.add_argument("--category", default=None)
    catalog.add_argument("--slot", default=None)
    catalog.add_argument("--race", default=None)
    catalog.set_defaults(func=cmd_character_catalog)

    sch = csub.add_parser("schema", help="Check (default) or --write the JSON Schema files generated from the dataclasses.")
    sch.add_argument("--write", action="store_true")
    sch.set_defaults(func=cmd_character_schema)

    build = csub.add_parser("build", help="Stage a recipe for the Unity batch build (the build itself arrives with M10).")
    build.add_argument("target")
    build.add_argument("--outfit", default=None)
    build.add_argument("--out", default="build/character")
    build.set_defaults(func=cmd_character_build)
