"""Host-side orchestration: load an asset module, produce a recipe, run the kernel, collect results.

Two cache keys keep iteration fast. The asset key covers geometry,
materials and quality: it names the output directory and decides whether
baked textures can be reused. The render key covers views, passes,
environment and engine: it names the renders subdirectory. Changing only
render settings therefore never repeats a bake.
"""

from __future__ import annotations

import glob
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, replace
from pathlib import Path

from . import KERNEL_VERSION
from .contact_sheet import make_contact_sheet
from .video import encode_frames
from .core import Asset, AssetGenerator, ExportSettings, ModelingError, RenderSettings, build_recipe, dump_recipe, recipe_hash

PROJECT_ROOT = Path(__file__).resolve().parent.parent
KERNEL_ENTRY = Path(__file__).resolve().parent / "kernel" / "entry.py"


class BlenderNotFound(RuntimeError):
    pass


def find_blender() -> str:
    """``PROMODELER_BLENDER`` wins; then PATH; then the standard Windows install locations."""
    env = os.environ.get("PROMODELER_BLENDER")
    if env:
        if os.path.isfile(env):
            return env
        raise BlenderNotFound(f"PROMODELER_BLENDER points to a missing file: {env}")
    on_path = shutil.which("blender")
    if on_path:
        return on_path
    candidates = sorted(glob.glob(r"C:\Program Files\Blender Foundation\Blender *\blender.exe"), reverse=True)
    if candidates:
        return candidates[0]
    raise BlenderNotFound("Blender was not found. Set PROMODELER_BLENDER to the blender executable.")


_version_cache: dict[str, str] = {}


def blender_version(executable: str) -> str:
    if executable in _version_cache:
        return _version_cache[executable]
    out = subprocess.run([executable, "--version"], capture_output=True, text=True, timeout=60, check=False)
    for line in out.stdout.splitlines():
        if line.startswith("Blender "):
            _version_cache[executable] = line.split()[1]
            return _version_cache[executable]
    raise BlenderNotFound(f"Could not read the Blender version from {executable}.")


def _merge_render(base: RenderSettings, override) -> RenderSettings:
    """A ``RenderSettings`` replaces the asset's settings; a dict replaces only the named fields."""
    if override is None:
        return base
    if isinstance(override, dict):
        return replace(base, **override)
    return override


@dataclass
class LoadedAsset:
    asset: Asset
    recipe: dict
    name: str


def load_asset_module(path: str):
    module_path = Path(path).resolve()
    if not module_path.is_file():
        raise ModelingError("asset.file", f"Asset file not found: {module_path}")
    spec = importlib.util.spec_from_file_location(f"promodeler_asset_{module_path.stem}", module_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def load_asset(path: str, render=None, quality_overrides: dict | None = None, formats=None) -> LoadedAsset:
    """An asset file exposes ``asset`` as an ``AssetGenerator`` or an ``Asset``; ``render`` and ``export`` are optional.

    ``quality_overrides`` replaces fields of the generator's quality profile,
    for example a lower texture resolution for a quick iteration. ``formats``
    overrides the export formats.
    """
    module = load_asset_module(path)
    target = getattr(module, "asset", None)
    base_render = getattr(module, "render", None) or RenderSettings()
    render = _merge_render(base_render, render)
    export = getattr(module, "export", None) or ExportSettings()
    if formats:
        export = ExportSettings(formats=tuple(formats))
    if isinstance(target, AssetGenerator):
        quality = replace(target.quality, **quality_overrides) if quality_overrides else None
        input = target.make_input(quality=quality)
        asset = target.generate(input)
        recipe = build_recipe(
            asset, input, render,
            parameters=target.parameters_recipe(input.parameters),
            generator_version=target.version, export=export,
        )
    elif isinstance(target, Asset):
        target.validate()
        asset = target
        recipe = build_recipe(asset, None, render, export=export)
    else:
        raise ModelingError("asset.module", f"{path} must define `asset` as an AssetGenerator or Asset.")
    return LoadedAsset(asset=asset, recipe=recipe, name=asset.name)


def slugify(name: str) -> str:
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in name.lower())


def asset_key(recipe: dict, blender: str) -> str:
    """Hash of everything except render and export settings, plus kernel and Blender versions."""
    without_render = {k: v for k, v in recipe.items() if k not in ("render", "export")}
    return recipe_hash(without_render, kernel_version=KERNEL_VERSION, blender=blender)


def render_key(recipe: dict) -> str:
    return recipe_hash({"render": recipe["render"], "export": recipe.get("export")}, kernel_version=KERNEL_VERSION)[:8]


@dataclass
class BuildResult:
    out_dir: Path
    report: dict
    cached: bool
    hash: str
    renders_dir: Path | None = None
    textures_reused: bool = False

    @property
    def ok(self) -> bool:
        return self.report.get("status") == "ok"


def _read_json(path: Path) -> dict | None:
    if not path.is_file():
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def build(path: str, out_root: str = "build", force: bool = False, render=None,
          timeout: float = 1800.0, quality_overrides: dict | None = None, formats=None) -> BuildResult:
    loaded = load_asset(path, render, quality_overrides, formats)
    blender = find_blender()
    version = blender_version(blender)
    digest = asset_key(loaded.recipe, version)
    rkey = render_key(loaded.recipe)
    out_dir = Path(out_root).resolve() / slugify(loaded.name) / digest[:12]
    renders_dir = out_dir / "renders" / rkey
    report_path = out_dir / "report.json"
    previous = _read_json(report_path)

    if previous and previous.get("status") == "ok" and previous.get("render_key") == rkey and not force:
        if all(Path(r["path"]).is_file() for r in previous.get("renders", [])):
            return BuildResult(out_dir=out_dir, report=previous, cached=True, hash=digest, renders_dir=renders_dir)

    reuse_textures = bool(previous and previous.get("status") == "ok" and (out_dir / "textures").is_dir() and not force)
    if force and out_dir.exists():
        shutil.rmtree(out_dir)
    if renders_dir.exists():
        shutil.rmtree(renders_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    recipe_path = out_dir / "recipe.json"
    with open(recipe_path, "w", encoding="utf-8") as f:
        f.write(dump_recipe(loaded.recipe))
    command = [blender, "-b", "--python", str(KERNEL_ENTRY), "--", str(PROJECT_ROOT), str(recipe_path), str(out_dir),
               str(renders_dir), "reuse" if reuse_textures else "bake"]
    started = time.perf_counter()
    completed = subprocess.run(command, capture_output=True, text=True, timeout=timeout, check=False,
                               encoding="utf-8", errors="replace")
    with open(out_dir / "blender.log", "w", encoding="utf-8") as f:
        f.write(completed.stdout)
        f.write("\n--- stderr ---\n")
        f.write(completed.stderr)
    report = _read_json(report_path)
    if report is None or "seconds" not in report:
        report = {
            "status": "failed",
            "error": {"code": "kernel.noReport", "message": f"Blender exited with {completed.returncode} without writing report.json. See blender.log."},
        }
    report["hash"] = digest
    report["render_key"] = rkey
    report["blender_exit_code"] = completed.returncode
    report["wall_seconds"] = round(time.perf_counter() - started, 3)
    if report.get("status") == "ok":
        for entry in report.get("renders", []):
            if entry.get("video") and entry.get("frames_dir"):
                encoded = encode_frames(entry["frames_dir"], entry.get("fps", 24), Path(entry["frames_dir"]))
                entry.update({"path": encoded["path"], "format": encoded["format"], "encoder": encoded["encoder"],
                              "written": entry["written"] and encoded["written"]})
        report["contact_sheet"] = make_contact_sheet(report, renders_dir / "contact_sheet.png")
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    return BuildResult(out_dir=out_dir, report=report, cached=False, hash=digest, renders_dir=renders_dir,
                       textures_reused=reuse_textures)


def latest_build_dir(path_or_dir: str, out_root: str = "build") -> Path:
    """Resolve an asset file to its most recently modified build directory, or pass a directory through."""
    candidate = Path(path_or_dir)
    if candidate.is_dir():
        return candidate.resolve()
    loaded = load_asset(str(candidate))
    asset_dir = Path(out_root).resolve() / slugify(loaded.name)
    builds = [p for p in asset_dir.glob("*") if (p / "report.json").is_file()]
    if not builds:
        raise FileNotFoundError(f"No builds found under {asset_dir}")
    return max(builds, key=lambda p: (p / "report.json").stat().st_mtime)


def clean(out_root: str = "build", keep: int = 1) -> list[Path]:
    """Delete all but the ``keep`` newest builds of every asset. Returns the removed directories."""
    removed = []
    root = Path(out_root)
    if not root.is_dir():
        return removed
    for asset_dir in root.iterdir():
        if not asset_dir.is_dir():
            continue
        builds = sorted(
            (p for p in asset_dir.iterdir() if p.is_dir()),
            key=lambda p: (p / "report.json").stat().st_mtime if (p / "report.json").is_file() else 0,
            reverse=True,
        )
        for stale in builds[keep:]:
            shutil.rmtree(stale)
            removed.append(stale)
    return removed
