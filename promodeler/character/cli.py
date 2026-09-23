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


def print_build(result: bridge.CharacterBuildResult) -> None:
    build = result.build
    print(f"hash:     {result.hash[:12]}{' (cached)' if result.cached else ''}")
    print(f"out:      {result.out_dir}")
    print(f"status:   {build.get('status')}")
    if not result.ok:
        error = build.get("error", {})
        print(f"error:    {error.get('code')}: {error.get('message')}")
        print(f"log:      {result.out_dir / 'unity.log'}")
        return
    env = build.get("environment", {})
    print(f"unity:    {env.get('unity')} hdrp {env.get('hdrp')} uma {env.get('uma')}")
    resolved = build.get("resolved", {})
    if resolved:
        residuals = ", ".join(f"{k} {v * 1000:+.0f} mm" for k, v in sorted((resolved.get("residuals_m") or {}).items()))
        print(f"resolved: race {resolved.get('race')}, {resolved.get('iterations')} iterations; residuals {residuals}")
    totals = build.get("totals", {})
    if totals:
        print(f"geometry: {totals.get('triangles')} tris, {totals.get('materials')} materials")
    for entry in build.get("wardrobe", []):
        resolved = entry.get("resolved") or ""
        state = "prop" if entry.get("fitted") and resolved.startswith("assets/") else "fitted" if entry.get("fitted") else "MISSING"
        print(f"wardrobe: {entry['slot']:9s} {entry.get('catalog_id')}  {state}")
    for render in build.get("renders", []):
        print(f"render:   {render.get('pass', 'shaded')}/{render['view']:<14} {'written' if render.get('written') else 'MISSING'}  {render['path']}")
    if build.get("contact_sheet"):
        print(f"sheet:    {build['contact_sheet']['path']}")
    for fmt, export in (build.get("exports") or {}).items():
        if isinstance(export, dict):
            print(f"export:   {fmt:<5} {'written' if export.get('written') else 'MISSING'} {export.get('bytes', 0)} bytes  {export.get('path')}")
        else:
            print(f"export:   {fmt:<5} {export}")
    for warning in build.get("warnings", []):
        print(f"warning:  {warning['code']}: {warning['message']}")
    print(f"seconds:  {build.get('wall_seconds', build.get('seconds'))}")


def cmd_character_build(args) -> int:
    if getattr(args, "all", False):
        return _build_all(args)
    if not args.target:
        raise ModelingError("character.build", "give a recipe id or --all.")
    path = resolve_recipe_path(args.target)
    recipe = load_recipe(path)
    if not isinstance(recipe, CharacterRecipe):
        raise ModelingError("character.build", f"{path} is an outfit; build its base character with --outfit {recipe.id}.")
    outfit = None
    if args.outfit:
        outfit = load_recipe(resolve_recipe_path(args.outfit))
        if not isinstance(outfit, OutfitRecipe):
            raise ModelingError("character.outfit", f"{args.outfit} is not an outfit recipe.")
    catalog = Catalog()
    print(f"recipe:   {path}")
    try:
        result = bridge.build(
            recipe, outfit, catalog, out_root=args.out, force=args.force,
            views=tuple(args.views.split(",")) if args.views else None, passes=tuple(args.passes.split(",")) if args.passes else None,
            formats=tuple(args.formats.split(",")) if args.formats else None, render=not args.no_render,
            log=print if args.verbose else None, probe=getattr(args, "probe", False),
        )
    except bridge.UnityNotFound as exc:
        print(f"error:    {exc}", file=sys.stderr)
        return 3
    print_build(result)
    return 0 if result.ok else 1


def cmd_character_setup(args) -> int:
    """Link UMA into the Unity project and run the editor-side setup (HDRP content import, UMA asset index)."""
    try:
        linked = bridge.link_uma()
    except bridge.UnityNotFound as exc:
        print(f"error:    {exc}", file=sys.stderr)
        return 3
    print(f"uma:      {linked['target']} -> {linked['source']} ({'created' if linked['created'] else 'already linked'}), version {linked['uma']}")
    try:
        hdrp = bridge.install_uma_hdrp_content()
    except bridge.UnityNotFound as exc:
        print(f"error:    {exc}", file=sys.stderr)
        return 3
    print(f"uma hdrp: {hdrp['written']} files written, {hdrp['unchanged']} unchanged, setup prefab {'present' if hdrp['setup_prefab'] else 'MISSING'}")
    if args.no_unity:
        return 0
    try:
        status = bridge.run_setup(log=print if args.verbose else None)
    except bridge.UnityNotFound as exc:
        print(f"error:    {exc}", file=sys.stderr)
        return 3
    for key in ("Ok", "UmaPresent", "HdrpContentPresent", "HdrpImported", "IndexRebuilt", "RaceMalePresent", "RaceFemalePresent", "Note", "Error", "error"):
        if key in status and status[key] not in (None, "", False):
            print(f"{key + ':':<20} {status[key]}")
    print(f"exit code:           {status.get('unity_exit_code')}  (log {status.get('log')})")
    if status.get("Note"):
        print("hint: run `promodeler character setup` once more so the imported UMA HDRP setup can apply.")
    return 0 if status.get("Ok") else 1


def _build_all(args) -> int:
    """Build every character recipe in turn (Unity locks the project, so builds are sequential)."""
    failures = 0
    args.all = False  # the per-recipe call below must not re-enter this loop
    for path in sorted(RECIPES_DIR.glob("*.json")):
        args.target = path.stem
        print(f"===== {path.stem} =====")
        code = cmd_character_build(args)
        failures += 1 if code else 0
    print(f"built {len(list(RECIPES_DIR.glob('*.json')))} recipes, {failures} failed")
    return 1 if failures else 0


def cmd_character_report(args) -> int:
    """One table of residuals over the newest build of every character (or the ids given)."""
    ids = args.ids or sorted(p.stem for p in RECIPES_DIR.glob("*.json"))
    keys = ["barefoot_height", "inseam", "shoulder_width", "foot_length", "head_height", "chest", "bust", "underbust", "waist", "hip"]
    rows = []
    for recipe_id in ids:
        builds = sorted((Path(args.out) / recipe_id).glob("*/build.json"), key=lambda p: p.stat().st_mtime)
        if not builds:
            rows.append((recipe_id, None, {}))
            continue
        build = json.loads(builds[-1].read_text(encoding="utf-8"))
        rows.append((recipe_id, build, (build.get("resolved") or {}).get("residuals_m") or {}))
    header = "| id | status | s | " + " | ".join(keys) + " |"
    lines = [header, "|" + " --- |" * (len(keys) + 3)]
    for recipe_id, build, residuals in rows:
        if build is None:
            lines.append(f"| {recipe_id} | (no build) | | " + " | ".join("" for _ in keys) + " |")
            continue
        cells = []
        for key in keys:
            if key in residuals:
                mm = residuals[key] * 1000
                cells.append(f"{mm:+.0f}" + ("" if abs(mm) <= (2 if key == "barefoot_height" else 5) else "*"))
            else:
                cells.append("")
        lines.append(f"| {recipe_id} | {build.get('status')} | {build.get('wall_seconds', build.get('seconds', 0)):.0f} | " + " | ".join(cells) + " |")
    text = "\n".join(lines)
    print("residuals in mm (* = outside tolerance: height 2 mm, others 5 mm)")
    print(text)
    if args.write:
        Path(args.write).write_text(text + "\n", encoding="utf-8")
        print(f"written: {args.write}")
    return 0


def cmd_character_edit(args) -> int:
    """Open the Unity character editor window on a recipe (interactive; returns as soon as the editor starts)."""
    import subprocess

    path = resolve_recipe_path(args.target)
    ready, reason = bridge.project_ready()
    if not ready:
        print(f"error:    {reason}", file=sys.stderr)
        return 3
    try:
        unity = bridge.find_unity()
    except bridge.UnityNotFound as exc:
        print(f"error:    {exc}", file=sys.stderr)
        return 3
    command = [unity, "-projectPath", str(bridge.UNITY_PROJECT), "-executeMethod", "ProModeler.Editor.CharacterEditorWindow.Open",
               "-recipe", str(path.resolve()), "-catalog", str(Catalog().root)]
    subprocess.Popen(command, cwd=str(bridge.UNITY_PROJECT))
    print(f"unity:    editor started on {path}")
    print("save in the window writes the recipe JSON only; then run `promodeler character validate` and `character diff`.")
    return 0


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
        for name, value in (("outfit", None), ("out", "build/character"), ("views", None), ("passes", None), ("formats", None),
                            ("no_render", False), ("verbose", False)):
            setattr(args, name, value)
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

    setup = csub.add_parser("setup", help="Link external/uma into the Unity project (Assets/UMA junction) and run the editor setup.")
    setup.add_argument("--no-unity", action="store_true", help="Only create the link; skip the editor-side setup.")
    setup.add_argument("--verbose", "-v", action="store_true")
    setup.set_defaults(func=cmd_character_setup)

    build = csub.add_parser("build", help="Build a character with the Unity + UMA batch pipeline and read back build.json.")
    build.add_argument("target", nargs="?", default=None, help="Character recipe id or path (omit with --all).")
    build.add_argument("--all", action="store_true", help="Build every character/recipes/*.json in turn.")
    build.add_argument("--outfit", default=None, help="Outfit recipe id to dress the character with.")
    build.add_argument("--out", default="build/character")
    build.add_argument("--force", action="store_true", help="Ignore the cached build and rebuild accessories.")
    build.add_argument("--views", default=None, help="Comma-separated: front,side,back,perspective,face,hand")
    build.add_argument("--passes", default=None, help="Comma-separated: shaded,clay")
    build.add_argument("--formats", default=None, help="Comma-separated: fbx,glb")
    build.add_argument("--no-render", action="store_true", help="Skip verification renders (runs Unity with -nographics).")
    build.add_argument("--probe", action="store_true", help="Also write calibration.json: each body parameter at 0 and 1 against every target.")
    build.add_argument("--verbose", "-v", action="store_true")
    build.set_defaults(func=cmd_character_build)

    edit = csub.add_parser("edit", help="Open the Unity character editor (sliders, preview, Save writes the recipe JSON).")
    edit.add_argument("target", help="Character recipe id or path.")
    edit.set_defaults(func=cmd_character_edit)

    report = csub.add_parser("report", help="Residual table over the newest builds (mm; * marks values outside tolerance).")
    report.add_argument("ids", nargs="*", help="Recipe ids (default: all recipes).")
    report.add_argument("--out", default="build/character")
    report.add_argument("--write", default=None, help="Also write the markdown table to this file.")
    report.set_defaults(func=cmd_character_report)
