from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import KERNEL_VERSION, __version__
from .build import BlenderNotFound, build, blender_version, clean, find_blender, latest_build_dir, load_asset
from .core import ModelingError, dump_recipe

TEMPLATE = '''"""{name}: describe the object here.

Run:  python -m promodeler build {path}
Quick iteration:  add --texture-resolution 256 --bake-samples 4
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from promodeler.core import (
    Asset, AssetGenerator, Bevel, Box, GenerationInput, Material, ModelingError, Part, RenderSettings,
    Transform, presets, srgb,
)


@dataclass(frozen=True)
class Parameters:
    width: float = 0.2
    height: float = 0.1
    depth: float = 0.15


def validate(p: Parameters) -> None:
    for name in ("width", "height", "depth"):
        if not 0.01 <= getattr(p, name) <= 5.0:
            raise ModelingError("{slug}.size", f"{{name}} must be within 0.01...5 m.")


def build(input: GenerationInput) -> Asset:
    p: Parameters = input.parameters
    paint = presets.painted_metal("paint", seed=input.seed, wear=0.5)
    body = Part(
        id="body",
        shape=Box(size=(p.width, p.height, p.depth)),
        material="paint",
        transform=Transform(translation=(0.0, p.height / 2, 0.0)),
        modifiers=(Bevel(width=0.003, segments=3),),
        smooth_angle=math.radians(40),
    )
    return Asset(name="{name}", materials=(paint,), parts=(body,))


asset = AssetGenerator(name="{name}", parameters=Parameters(), build=build, validate=validate, seed=1)
render = RenderSettings(resolution=640, views=("perspective", "front"), passes=("shaded", "clay"))
'''


def _render_overrides(args) -> dict | None:
    """Only the render fields given on the command line, layered over the asset's own settings."""
    fields = {}
    if args.resolution:
        fields["resolution"] = args.resolution
    if args.engine:
        fields["engine"] = args.engine
    if args.views:
        fields["views"] = tuple(args.views.split(","))
    if getattr(args, "passes", None):
        fields["passes"] = tuple(args.passes.split(","))
    if getattr(args, "environment", None):
        fields["environment"] = args.environment
    if getattr(args, "pose", None):
        fields["pose"] = args.pose
    if getattr(args, "clip", None):
        fields["clip"] = args.clip
    if getattr(args, "clip_fps", None):
        fields["clip_fps"] = args.clip_fps
    return fields or None


def _quality_overrides(args) -> dict | None:
    overrides = {}
    if getattr(args, "texture_resolution", None):
        overrides["texture_resolution"] = args.texture_resolution
    if getattr(args, "bake_samples", None):
        overrides["bake_samples"] = args.bake_samples
    return overrides or None


def cmd_doctor(args) -> int:
    print(f"promodeler {__version__} (kernel {KERNEL_VERSION}), host python {sys.version.split()[0]}")
    try:
        blender = find_blender()
        print(f"blender: {blender}")
        print(f"blender version: {blender_version(blender)}")
    except BlenderNotFound as exc:
        print(f"blender: NOT FOUND ({exc})")
        return 1
    try:
        import PIL  # noqa: F401
        print("pillow: available (contact sheets enabled)")
    except ImportError:
        print("pillow: missing (contact sheets disabled; pip install pillow)")
    try:
        import anthropic  # noqa: F401
        print("anthropic: available (critique enabled)")
    except ImportError:
        print("anthropic: missing (critique disabled; pip install anthropic)")
    from .character import bridge as character_bridge
    from .character.catalog import Catalog

    try:
        catalog = Catalog()
        print(f"catalog: version {catalog.version}, {len(catalog.entries)} entries ({catalog.root})")
    except ModelingError as exc:
        print(f"catalog: NOT LOADED ({exc.message})")
    try:
        print(f"unity: {character_bridge.find_unity()}")
    except character_bridge.UnityNotFound as exc:
        print(f"unity: NOT FOUND ({exc}); character builds need it from M10 on")
    project = character_bridge.project_version()
    print(f"unity project: {project or 'not created yet (unity/ProModelerCharacterCreator, M10)'}"
          + (f", uma {character_bridge.uma_version() or 'unknown'}" if project else ""))
    return 0


def cmd_recipe(args) -> int:
    loaded = load_asset(args.asset, _render_overrides(args), _quality_overrides(args))
    print(dump_recipe(loaded.recipe) if args.compact else json.dumps(loaded.recipe, indent=2, sort_keys=True))
    return 0


def print_report(result) -> None:
    report = result.report
    print(f"asset:   {report.get('asset', '?')}")
    print(f"hash:    {result.hash[:12]}{' (cached)' if result.cached else ''}")
    print(f"out:     {result.out_dir}")
    print(f"status:  {report.get('status')}")
    if not result.ok:
        return
    totals = report["totals"]
    print(f"geometry: {totals['triangles']} tris, {totals['vertices']} verts, "
          f"{totals['non_manifold_edges']} non-manifold edges, {len(report['parts'])} parts")
    bounds = report.get("bounds")
    if bounds:
        size = [round(hi - lo, 4) for lo, hi in zip(bounds["min"], bounds["max"])]
        print(f"bounds:  size {size} (Y up)")
    for part_id, stats in report["parts"].items():
        if "textures" in stats:
            channels = ", ".join(
                f"{c} {'cached' if m.get('cached') else str(m['seconds']) + 's'}" for c, m in stats["textures"].items())
            uv = stats.get("uv", {})
            print(f"bake:    {part_id}: {channels}; uv coverage {uv.get('coverage')}, {uv.get('texel_density_px_per_m')} px/m")
    for render in report.get("renders", []):
        state = "written" if render["written"] else "MISSING"
        label = f"{render.get('pass', 'shaded')}/{render['view']}"
        if render.get("video"):
            label = f"clip {render['clip']}/{render['view']}"
            print(f"video:   {label:<22} {state} {render['frames']} frames @ {render['fps']} fps "
                  f"({render.get('encoder') or 'no encoder'}) {render['seconds']}s  {render['path']}")
            continue
        print(f"render:  {label:<22} {state} {render['seconds']}s  {render['path']}")
    if report.get("contact_sheet"):
        print(f"sheet:   {report['contact_sheet']['path']}")
    for fmt, export in (report.get("exports") or {"glb": report.get("export", {})}).items():
        print(f"export:  {fmt:<5} {'written' if export.get('written') else 'MISSING'} {export.get('bytes', 0)} bytes  {export.get('path')}")
    rig_info = report.get("rig")
    if rig_info:
        clips = ", ".join(f"{c['id']} ({c['duration']}s)" for c in rig_info["clips"]) or "none"
        print(f"rig:     {rig_info['joints']} joints, skinned {rig_info['skinned'] or 'none'}, clips {clips}")
    for part_id, stats in report["parts"].items():
        for lod in stats.get("lods", []):
            print(f"lod:     {part_id} level {lod['level']} at {lod['distance']} m: {lod.get('triangles')} tris")
    for warning in report.get("warnings", []):
        print(f"warning: {warning['code']}: {warning['message']}")
    print(f"seconds: {report.get('wall_seconds', report.get('seconds'))}")


def cmd_build(args) -> int:
    result = build(args.asset, out_root=args.out, force=args.force, render=_render_overrides(args),
                   quality_overrides=_quality_overrides(args),
                   formats=tuple(args.formats.split(",")) if getattr(args, "formats", None) else None)
    print_report(result)
    if not result.ok:
        error = result.report.get("error", {})
        print(f"error:   {error.get('code')}: {error.get('message')}")
        if args.verbose and error.get("traceback"):
            print(error["traceback"])
        print(f"log:     {result.out_dir / 'blender.log'}")
        return 1
    return 0


def cmd_critique(args) -> int:
    from .critique import critique_build, format_critique

    out_dir = latest_build_dir(args.target, args.out)
    try:
        critique = critique_build(out_dir, reference=args.reference, goal=args.goal, model=args.model,
                                  fallbacks=not args.no_fallback)
    except (RuntimeError, FileNotFoundError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:  # noqa: BLE001 - API/auth failures are reported, not traced.
        print(f"error: critique request failed ({type(exc).__name__}): {exc}", file=sys.stderr)
        print("hint: authenticate with `ant auth login` or set ANTHROPIC_API_KEY.", file=sys.stderr)
        return 1
    print(f"build:    {out_dir}")
    print(f"model:    {critique.get('model')}")
    print(format_critique(critique))
    print(f"written:  {out_dir / 'critique.json'}")
    return 0


def cmd_clean(args) -> int:
    removed = clean(args.out, keep=args.keep)
    for path in removed:
        print(f"removed: {path}")
    print(f"{len(removed)} build directories removed")
    return 0


def cmd_new(args) -> int:
    path = Path(args.path)
    if path.exists():
        print(f"error: {path} already exists", file=sys.stderr)
        return 1
    name = args.name or path.stem.replace("_", " ").title()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(TEMPLATE.format(name=name, path=path.as_posix(), slug=path.stem), encoding="utf-8")
    print(f"created: {path}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="promodeler", description="Code-first realistic 3D asset generation.")
    sub = parser.add_subparsers(dest="command", required=True)

    doctor = sub.add_parser("doctor", help="Check the host environment, Blender and optional packages.")
    doctor.set_defaults(func=cmd_doctor)

    for name, func, help_text in (
        ("recipe", cmd_recipe, "Print the canonical recipe JSON without running Blender."),
        ("build", cmd_build, "Generate, bake, render and export an asset."),
    ):
        p = sub.add_parser(name, help=help_text)
        p.add_argument("asset", help="Path to an asset .py file exposing `asset`.")
        p.add_argument("--resolution", type=int, default=None)
        p.add_argument("--engine", choices=("eevee", "cycles"), default=None)
        p.add_argument("--views", default=None, help="Comma-separated: perspective,front,side,top")
        p.add_argument("--passes", default=None, help="Comma-separated: shaded,clay,wireframe,normals,uv")
        p.add_argument("--environment", default=None, help="studio, overcast, sunny, sunset or an .hdr/.exr path")
        p.add_argument("--pose", default=None, help="Render the rig in this pose")
        p.add_argument("--clip", default=None, help="Render this clip as an .mp4 per view instead of stills")
        p.add_argument("--clip-fps", type=int, default=None, help="Frame rate of clip videos (default 24)")
        p.add_argument("--texture-resolution", type=int, default=None, help="Override quality.texture_resolution")
        p.add_argument("--bake-samples", type=int, default=None, help="Override quality.bake_samples")
        p.add_argument("--formats", default=None, help="Comma-separated export formats: glb,usdz")
        p.set_defaults(func=func)
    sub.choices["recipe"].add_argument("--compact", action="store_true")
    sub.choices["build"].add_argument("--out", default="build")
    sub.choices["build"].add_argument("--force", action="store_true", help="Ignore the cache, including baked textures.")
    sub.choices["build"].add_argument("--verbose", "-v", action="store_true")

    critique = sub.add_parser("critique", help="Ask Claude to review the latest build of an asset (needs the anthropic package).")
    critique.add_argument("target", help="Asset .py file (uses its newest build) or a build directory.")
    critique.add_argument("--reference", default=None, help="Reference photo to compare against.")
    critique.add_argument("--goal", default=None, help="What the asset is meant to look like.")
    critique.add_argument("--model", default="claude-opus-5")
    critique.add_argument("--no-fallback", action="store_true", help="Disable server-side refusal fallbacks.")
    critique.add_argument("--out", default="build")
    critique.set_defaults(func=cmd_critique)

    cleaner = sub.add_parser("clean", help="Delete stale build directories.")
    cleaner.add_argument("--out", default="build")
    cleaner.add_argument("--keep", type=int, default=1, help="Newest builds to keep per asset.")
    cleaner.set_defaults(func=cmd_clean)

    new = sub.add_parser("new", help="Create an asset file from a template.")
    new.add_argument("path", help="Where to create it, e.g. assets/lamp.py")
    new.add_argument("--name", default=None)
    new.set_defaults(func=cmd_new)

    from .character.cli import add_parsers as add_character_parsers

    add_character_parsers(sub)

    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except ModelingError as exc:
        print(f"error: {exc.code}: {exc.message}", file=sys.stderr)
        return 2
    except BlenderNotFound as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
