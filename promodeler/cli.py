from __future__ import annotations

import argparse
import json
import sys

from . import KERNEL_VERSION, __version__
from .build import BlenderNotFound, build, blender_version, find_blender, load_asset
from .core import ModelingError, RenderSettings, dump_recipe


def _render_overrides(args) -> RenderSettings | None:
    if args.resolution is None and args.engine is None and args.views is None:
        return None
    base = RenderSettings()
    return RenderSettings(
        resolution=args.resolution or base.resolution,
        engine=args.engine or base.engine,
        views=tuple(args.views.split(",")) if args.views else base.views,
        samples=base.samples,
        background=base.background,
    )


def cmd_doctor(args) -> int:
    print(f"promodeler {__version__} (kernel {KERNEL_VERSION}), host python {sys.version.split()[0]}")
    try:
        blender = find_blender()
        print(f"blender: {blender}")
        print(f"blender version: {blender_version(blender)}")
    except BlenderNotFound as exc:
        print(f"blender: NOT FOUND ({exc})")
        return 1
    return 0


def _quality_overrides(args) -> dict | None:
    overrides = {}
    if getattr(args, "texture_resolution", None):
        overrides["texture_resolution"] = args.texture_resolution
    if getattr(args, "bake_samples", None):
        overrides["bake_samples"] = args.bake_samples
    return overrides or None


def cmd_recipe(args) -> int:
    loaded = load_asset(args.asset, _render_overrides(args), _quality_overrides(args))
    print(dump_recipe(loaded.recipe) if args.compact else json.dumps(loaded.recipe, indent=2, sort_keys=True))
    return 0


def cmd_build(args) -> int:
    result = build(args.asset, out_root=args.out, force=args.force, render=_render_overrides(args),
                   quality_overrides=_quality_overrides(args))
    report = result.report
    print(f"asset:   {report.get('asset', '?')}")
    print(f"hash:    {result.hash[:12]}{' (cached)' if result.cached else ''}")
    print(f"out:     {result.out_dir}")
    print(f"status:  {report.get('status')}")
    if not result.ok:
        error = report.get("error", {})
        print(f"error:   {error.get('code')}: {error.get('message')}")
        if args.verbose and error.get("traceback"):
            print(error["traceback"])
        print(f"log:     {result.out_dir / 'blender.log'}")
        return 1
    totals = report["totals"]
    print(f"geometry: {totals['triangles']} tris, {totals['vertices']} verts, "
          f"{totals['non_manifold_edges']} non-manifold edges, {len(report['parts'])} parts")
    bounds = report.get("bounds")
    if bounds:
        size = [round(hi - lo, 4) for lo, hi in zip(bounds["min"], bounds["max"])]
        print(f"bounds:  size {size} (Y up)")
    for part_id, stats in report["parts"].items():
        if "textures" in stats:
            channels = ", ".join(f"{c} {m['seconds']}s" for c, m in stats["textures"].items())
            uv = stats.get("uv", {})
            print(f"bake:    {part_id}: {channels}; uv coverage {uv.get('coverage')}, {uv.get('texel_density_px_per_m')} px/m")
    for render in report.get("renders", []):
        state = "written" if render["written"] else "MISSING"
        print(f"render:  {render['view']:<12} {state} {render['seconds']}s  {render['path']}")
    export = report.get("export", {})
    print(f"export:  {'written' if export.get('written') else 'MISSING'} {export.get('bytes', 0)} bytes  {export.get('path')}")
    for warning in report.get("warnings", []):
        print(f"warning: {warning['code']}: {warning['message']}")
    print(f"seconds: {report.get('seconds')}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="promodeler", description="Code-first realistic 3D asset generation.")
    sub = parser.add_subparsers(dest="command", required=True)

    doctor = sub.add_parser("doctor", help="Check the host environment and Blender.")
    doctor.set_defaults(func=cmd_doctor)

    for name, func, help_text in (
        ("recipe", cmd_recipe, "Print the canonical recipe JSON without running Blender."),
        ("build", cmd_build, "Generate, render and export an asset."),
    ):
        p = sub.add_parser(name, help=help_text)
        p.add_argument("asset", help="Path to an asset .py file exposing `asset`.")
        p.add_argument("--resolution", type=int, default=None)
        p.add_argument("--engine", choices=("eevee", "cycles"), default=None)
        p.add_argument("--views", default=None, help="Comma-separated: perspective,front,side,top")
        p.add_argument("--texture-resolution", type=int, default=None, help="Override quality.texture_resolution")
        p.add_argument("--bake-samples", type=int, default=None, help="Override quality.bake_samples")
        p.set_defaults(func=func)
    sub.choices["recipe"].add_argument("--compact", action="store_true")
    sub.choices["build"].add_argument("--out", default="build")
    sub.choices["build"].add_argument("--force", action="store_true", help="Ignore the cache.")
    sub.choices["build"].add_argument("--verbose", "-v", action="store_true")

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
